import os
from dotenv import load_dotenv
import streamlit as st
import xml.etree.ElementTree as ET
import folium
from streamlit_folium import folium_static
import io, json, openai
import pandas as pd
import openrouteservice
from route_optimizer import optimize_route
from streamlit_sortables import sort_items

# 0) Carrega variáveis de ambiente
load_dotenv()
openai.api_key = st.secrets.get("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY", "")
ors_key        = st.secrets.get("ORS_API_KEY")    or os.getenv("ORS_API_KEY", "")
if not openai.api_key:
    st.sidebar.error("🔑 Defina OPENAI_API_KEY")
    st.stop()
if not ors_key:
    st.sidebar.warning("⚠️ ORS_API_KEY não encontrado — rotas serão traçadas em linha reta")
ors_client = openrouteservice.Client(key=ors_key) if ors_key else None

# Contador de chamadas ORS (para debug)
if "ors_count" not in st.session_state:
    st.session_state["ors_count"] = 0

@st.cache_data(ttl=24*3600)
def get_route_geojson(coords: tuple) -> dict:
    st.session_state["ors_count"] += 1
    print(f"➡️ ORS chamadas: {st.session_state['ors_count']}")
    return ors_client.directions(
        coordinates=list(coords),
        profile="driving-car",
        format="geojson"
    )

# 1) Layout
st.set_page_config(page_title="Visualizador de Rotas", layout="wide")
st.title("🌐 Visualizador de Rotas")

# 2) Upload + parse do KML
st.sidebar.header("🔎 Navegar / Reordenar")
uploaded = st.sidebar.file_uploader("Envie seu arquivo .kml", type=["kml"])
if not uploaded:
    st.sidebar.info("Envie um .kml para começar")
    st.stop()

raw = uploaded.read()
root = ET.fromstring(raw if isinstance(raw, str) else raw.decode("utf-8"))
NS   = {"k": "http://www.opengis.net/kml/2.2"}
doc  = root.find("k:Document", NS)
if doc is None:
    st.sidebar.error("KML inválido: <Document> não encontrado")
    st.stop()

# 3) Extrai Semanas→Dias→Placemarks + lista de todos os clientes
semanas     = {}
all_clients = set()
for wk in doc.findall("k:Folder", NS):
    wkname = (wk.findtext("k:name", namespaces=NS) or "").strip().replace(" ", "_")
    dias = {}
    for day in wk.findall("k:Folder", NS):
        dname = (day.findtext("k:name", namespaces=NS) or "").strip().replace(" ", "_")
        pts = []
        for pm in day.findall("k:Placemark", NS):
            nm = (pm.findtext("k:name", namespaces=NS) or "").strip()
            co = (pm.findtext("k:Point/k:coordinates", namespaces=NS) or "").strip()
            if not nm or not co:
                continue
            lon, lat, *_ = co.split(",")
            pts.append({"name": nm, "lat": float(lat), "lon": float(lon)})
            all_clients.add(nm)
        dias[dname] = pts
    semanas[wkname] = dias

if not semanas:
    st.sidebar.error("Nenhuma rota encontrada no KML.")
    st.stop()

# 4) Cliente inicial global (usado no “otimizar tudo”)
#start_global = st.sidebar.selectbox("Cliente inicial (para todas as rotas)", sorted(all_clients))

# 5) Seleção de Semana / Dia
sem_sel    = st.sidebar.selectbox("Semana", sorted(semanas.keys()))
dia_sel    = st.sidebar.selectbox("Dia",    sorted(semanas[sem_sel].keys()))
placemarks = semanas[sem_sel][dia_sel]
if not placemarks:
    st.sidebar.warning("Nenhum cliente neste dia")
    st.stop()

# 6) Busca + filtro de cliente neste dia
search_term = st.sidebar.text_input("🔎 Buscar cliente (código ou nome)")
filtered = [(i,p) for i,p in enumerate(placemarks) if search_term.lower() in p["name"].lower()]
if filtered:
    choose_list = [f"{i+1:02d} – {p['name']}" for i,p in filtered]
else:
    choose_list = [f"{i+1:02d} – {p['name']}" for i,p in enumerate(placemarks)]
initial = st.sidebar.selectbox("Cliente inicial deste dia", choose_list)
init_idx = int(initial.split("–")[0].strip()) - 1

# 7) Session state para a ordem do dia
order_key = f"order_{sem_sel}_{dia_sel}"
if order_key not in st.session_state or len(st.session_state[order_key]) != len(placemarks):
    st.session_state[order_key] = list(range(len(placemarks)))
order_full = st.session_state[order_key]

# 8) Drag-and-drop para reordenar livremente
st.sidebar.markdown("### 🚚 Arraste para reordenar")
with st.sidebar:
    names       = [placemarks[i]["name"] for i in order_full]
    sorted_names = sort_items(
        names,
        header="Ordem de visitas",
        direction="vertical",
        key=f"sort_{order_key}"
    )
new_order = [ next(idx for idx,p in enumerate(placemarks) if p["name"]==nm) for nm in sorted_names ]
st.session_state[order_key] = new_order
order_full = new_order

# 9) Garante que o cliente inicial vá para a posição 0
if init_idx in order_full:
    order_full.remove(init_idx)
order_full.insert(0, init_idx)
st.session_state[order_key] = order_full

# 10) Filtrar o que aparece no mapa / filtro multiselect
st.sidebar.markdown("### 🔍 Mostrar apenas estas")
prefixes = [f"{i+1:02d} – {placemarks[i]['name']}" for i in order_full]
sel = st.sidebar.multiselect("Visitas", prefixes, default=prefixes)
pref2idx = {prefixes[i]: order_full[i] for i in range(len(prefixes))}
visible  = [pref2idx[p] for p in prefixes if p in sel]
if not visible:
    st.sidebar.warning("Marque ao menos uma visita")
    st.stop()

# 11) Contexto
first_name = placemarks[visible[0]]["name"]
st.subheader(f"Centralizando: **{sem_sel} / {dia_sel} → {first_name}**")

# 12) Botão: recalcular apenas este dia
if st.sidebar.button("🚀 Recalcular rota deste dia"):
    with st.spinner("Otimizando o dia selecionado…"):
        resp = openai.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role":"system","content":"Decida boa estratégia e tempo (≤300ms)."},
                {"role":"user","content":f"Otimize este dia começando em {placemarks[init_idx]['name']}."}
            ],
            functions=[{
                "name":"optimize_route",
                "description":"Reordena rota minimizando distância",
                "parameters":{
                    "type":"object",
                    "properties":{
                        "strategy":{"type":"string","enum":["PATH_CHEAPEST_ARC","PARALLEL_CHEAPEST_INSERTION","AUTOMATIC"]},
                        "time_limit_ms":{"type":"integer","minimum":0}
                    },
                    "required":["strategy","time_limit_ms"]
                }
            }],
            function_call={"name":"optimize_route"}
        )
        args = json.loads(resp.choices[0].message.function_call.arguments)
        # Chama optimize_route já com start_index=init_idx
        ids = optimize_route(
            [{"id":p["name"],"lat":p["lat"],"lon":p["lon"]} for p in placemarks],
            strategy=args["strategy"],
            time_limit_ms=args["time_limit_ms"],
            start_index=init_idx
        )
        # converte de volta para índices na ordem correta
        idx_map = {p["name"]: i for i,p in enumerate(placemarks)}
        st.session_state[order_key] = [idx_map[nm] for nm in ids]
        st.rerun()

# Use o primeiro cliente disponível como "start_global"
start_global = None
for wk, dias in semanas.items():
    for dy, pts in dias.items():
        if pts:
            start_global = pts[0]["name"]
            break
    if start_global:
        break
if not start_global:
    start_global = "Nenhum"
# 13) Botão: otimizar todas as semanas/dias
if st.sidebar.button("🚀 Otimizar todas as rotas com IA"):
    with st.spinner("Otimizando tudo…"):
        # chamada única
        resp = openai.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role":"system","content":"Decida estratégia e tempo (≤300ms)."},
                {"role":"user","content":f"Otimize todo o roteiro começando em {start_global} para cada dia."}
            ],
            functions=[{
                "name":"optimize_route",
                "description":"Reordena rota minimizando distância",
                "parameters":{
                    "type":"object",
                    "properties":{
                        "strategy":{"type":"string","enum":["PATH_CHEAPEST_ARC","PARALLEL_CHEAPEST_INSERTION","AUTOMATIC"]},
                        "time_limit_ms":{"type":"integer","minimum":0}
                    },
                    "required":["strategy","time_limit_ms"]
                }
            }],
            function_call={"name":"optimize_route"}
        )
        args = json.loads(resp.choices[0].message.function_call.arguments)
        total = sum(len(d) for d in semanas.values())
        bar   = st.progress(0)
        cnt   = 0
        for wk,dias in semanas.items():
            for dy,pts in dias.items():
                if not pts: continue
                # coloca start_global à frente
                pts2 = pts.copy()
                if start_global in [p["name"] for p in pts2]:
                    j = next(i for i,p in enumerate(pts2) if p["name"]==start_global)
                    pts2[0], pts2[j] = pts2[j], pts2[0]
                ids = optimize_route(
                    [{"id":p["name"],"lat":p["lat"],"lon":p["lon"]} for p in pts2],
                    strategy=args["strategy"],
                    time_limit_ms=args["time_limit_ms"]
                )
                # converte para índices originais
                mp = {p["name"]: i for i,p in enumerate(pts2)}
                st.session_state[f"order_{wk}_{dy}"] = [mp[nm] for nm in ids]
                cnt += 1; bar.progress(cnt/total)
        st.success("✅ Todas as rotas otimizadas!")

# 14) Monta CSV unificado
rows = []
for wk,dias in semanas.items():
    for dy,pts in dias.items():
        key = f"order_{wk}_{dy}"
        if key not in st.session_state: continue
        for o,idx in enumerate(st.session_state[key], start=1):
            rows.append({
                "cod": pts[idx]["name"],
                "numero_semana": int(wk.split("_")[-1]),
                "dia_semana":   int(dy.split("_")[-1]),
                "ordem_visita": o
            })
csv_bytes = pd.DataFrame(rows).to_csv(index=False, sep=";").encode("utf-8")
st.sidebar.download_button("📥 Baixar CSV completo", csv_bytes, "rotas.csv", "text/csv")

# 15) Renderiza mapa só para o dia atual
m = folium.Map(
    location=[placemarks[visible[0]]["lat"], placemarks[visible[0]]["lon"]],
    zoom_start=14
)
coords = [(placemarks[i]["lon"], placemarks[i]["lat"]) for i in visible]
fg = folium.FeatureGroup(name=f"Rota {sem_sel}/{dia_sel}", show=True)
if ors_client and len(coords)>1:
    try:
        gj = get_route_geojson(tuple(coords))
        folium.GeoJson(gj, style_function=lambda f:{"color":"blue","weight":4,"opacity":0.7}).add_to(fg)
    except:
        folium.PolyLine([(lat,lon) for lon,lat in coords], color="blue", weight=4, opacity=0.7).add_to(fg)
else:
    folium.PolyLine([(lat,lon) for lon,lat in coords], color="blue", weight=4, opacity=0.7).add_to(fg)
m.add_child(fg)
for seq,idx in enumerate(visible,start=1):
    p = placemarks[idx]
    folium.Marker(
        [p["lat"], p["lon"]],
        popup=f"{seq:02d} – {p['name']}",
        icon=folium.Icon(color="red", icon="info-sign")
    ).add_to(m)
c = placemarks[visible[0]]
folium.CircleMarker(
    [c["lat"], c["lon"]],
    radius=8, color="yellow",
    fill=True, fill_color="yellow", fill_opacity=0.8
).add_to(m)
folium.LayerControl(collapsed=False).add_to(m)
folium_static(m, width=1200, height=700)

# 16) Salvar KML Ajustado
def build_kml(pts, idxs):
    k = ET.Element("kml", xmlns=NS["k"])
    d = ET.SubElement(k, "Document")
    ET.SubElement(d, "name").text = f"Roteiro {sem_sel}/{dia_sel} (ajustado)"
    wkf=ET.SubElement(d,"Folder"); ET.SubElement(wkf,"name").text=sem_sel
    dyf=ET.SubElement(wkf,"Folder"); ET.SubElement(dyf,"name").text=dia_sel
    for s,i in enumerate(idxs, start=1):
        p=pts[i]
        pm=ET.SubElement(dyf,"Placemark"); ET.SubElement(pm,"name").text=p["name"]
        pt=ET.SubElement(pm,"Point"); ET.SubElement(pt,"coordinates").text=f"{p['lon']},{p['lat']},0"
    buf=io.BytesIO(); ET.ElementTree(k).write(buf,encoding="utf-8",xml_declaration=True)
    return buf.getvalue()

st.sidebar.markdown("---")
if st.sidebar.button("💾 Salvar KML Ajustado"):
    kb = build_kml(placemarks, visible)
    st.sidebar.download_button("📥 Baixar KML", kb, f"rota_{sem_sel}_{dia_sel}.kml", "application/vnd.google-earth.kml+xml")
