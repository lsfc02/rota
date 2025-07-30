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

# 0) carrega .env
load_dotenv()

# 1) API Keys
openai.api_key = st.secrets.get("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY", "")
ors_key        = st.secrets.get("ORS_API_KEY")    or os.getenv("ORS_API_KEY", "")
if not openai.api_key:
    st.sidebar.error("🔑 Defina OPENAI_API_KEY")
    st.stop()
if not ors_key:
    st.sidebar.warning("⚠️ ORS_API_KEY não encontrado – rota seguirá linha reta")
ors_client = openrouteservice.Client(key=ors_key) if ors_key else None

# contador ORS (para debug no terminal)
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

# 2) Layout
st.set_page_config(page_title="Visualizador de Rotas", layout="wide")
st.title("🌐 Visualizador de Rotas")

# 3) Upload + parse KML
st.sidebar.header("🔎 Navegar / Reordenar")
uploaded = st.sidebar.file_uploader("Envie seu arquivo .kml", type=["kml"])
if not uploaded:
    st.sidebar.info("Envie um .kml para começar")
    st.stop()

raw = uploaded.read()
try:
    root = ET.fromstring(raw)
except:
    root = ET.fromstring(raw.decode("utf-8"))

NS  = {"k": "http://www.opengis.net/kml/2.2"}
doc = root.find("k:Document", NS)
if doc is None:
    st.sidebar.error("KML inválido: <Document> não encontrado")
    st.stop()

# 4) Extrai Semanas → Dias → Placemarks
semanas = {}
for wk in doc.findall("k:Folder", NS):
    wkname = (wk.findtext("k:name", namespaces=NS) or "").strip().replace(" ", "_")
    dias = {}
    for day in wk.findall("k:Folder", NS):
        dname = (day.findtext("k:name", namespaces=NS) or "").strip().replace(" ", "_")
        pts = []
        for pm in day.findall("k:Placemark", NS):
            name   = (pm.findtext("k:name", namespaces=NS) or "").strip()
            coords = (pm.findtext("k:Point/k:coordinates", namespaces=NS) or "").strip()
            if not name or not coords:
                continue
            lon, lat, *_ = coords.split(",")
            pts.append({"name": name, "lat": float(lat), "lon": float(lon)})
        dias[dname] = pts
    semanas[wkname] = dias

if not semanas:
    st.sidebar.error("Nenhuma rota encontrada no KML.")
    st.stop()

# 5) Seleção Semana / Dia
sem_sel    = st.sidebar.selectbox("Semana", sorted(semanas.keys()))
dia_sel    = st.sidebar.selectbox("Dia",    sorted(semanas[sem_sel].keys()))
placemarks = semanas[sem_sel][dia_sel]
if not placemarks:
    st.sidebar.warning("Nenhum cliente neste dia")
    st.stop()

# 6) Session-state para ordem
order_key = f"order_{sem_sel}_{dia_sel}"
if order_key not in st.session_state or len(st.session_state[order_key]) != len(placemarks):
    st.session_state[order_key] = list(range(len(placemarks)))
order = st.session_state[order_key]

# 7) Reordenação manual
st.sidebar.markdown("### 🔀 Reordenar visitas")
labels    = [f"{i+1:02d} – {placemarks[idx]['name']}" for i, idx in enumerate(order)]
sel_label = st.sidebar.selectbox("Selecionar visita", labels, key=order_key+"_sel")
sel_i     = labels.index(sel_label)
c1, c2    = st.sidebar.columns(2)
if c1.button("⬆️ Mover para Cima") and sel_i > 0:
    order[sel_i-1], order[sel_i] = order[sel_i], order[sel_i-1]
    st.session_state[order_key] = order
if c2.button("⬇️ Mover para Baixo") and sel_i < len(order)-1:
    order[sel_i+1], order[sel_i] = order[sel_i], order[sel_i+1]
    st.session_state[order_key] = order
if st.sidebar.button("🔄 Resetar ordem"):
    st.session_state[order_key] = list(range(len(placemarks)))
    order = st.session_state[order_key]

# 8) Filtrar visitas visíveis (label corrigido)
st.sidebar.markdown("### 🔍 Filtrar visitas visíveis")
mostrar = st.sidebar.multiselect(
    "Mostrar apenas estas visitas",
    options=labels,
    default=labels
)
mostrar_idxs = [order[i] for i, lab in enumerate(labels) if lab in mostrar]
if not mostrar_idxs:
    st.sidebar.warning("Marque ao menos uma visita")
    st.stop()

# 9) Contexto
first = placemarks[mostrar_idxs[0]]["name"]
st.subheader(f"Centralizando: **{sem_sel} / {dia_sel} → {first}**")

# 10) Otimização via IA para TODAS as semanas/dias
functions = [{
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
}]
if st.sidebar.button("🚀 Otimizar todas as rotas com IA"):
    with st.spinner("⏳ Otimizando todas as rotas..."):
        resp = openai.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role":"system","content":"Decida estratégia e tempo (≤300ms)."},
                {"role":"user","content":"Otimize com heurísticas avançadas para todos os dias/semanais."}
            ],
            functions=functions,
            function_call={"name":"optimize_route"}
        )
        args  = json.loads(resp.choices[0].message.function_call.arguments)
        total = sum(len(d) for d in semanas.values())
        pbar  = st.progress(0)
        cnt   = 0

        # loop em todas as semanas e dias
        for wk, dias in semanas.items():
            for dy, pts in dias.items():
                if not pts:
                    continue
                ids = optimize_route(
                    [{"id": p["name"], "lat": p["lat"], "lon": p["lon"]} for p in pts],
                    strategy=args["strategy"],
                    time_limit_ms=args["time_limit_ms"]
                )
                idx_map = {p["name"]: i for i, p in enumerate(pts)}
                st.session_state[f"order_{wk}_{dy}"] = [idx_map[x] for x in ids]
                cnt += 1
                pbar.progress(cnt / total)

        st.success("✅ Todas as rotas foram otimizadas com IA!")

        # gera CSV completo
        rows = []
        for wk, dias in semanas.items():
            for dy, pts in dias.items():
                key  = f"order_{wk}_{dy}"
                ordem = st.session_state.get(key, [])
                for o, idx in enumerate(ordem, start=1):
                    rows.append({
                        "cod": pts[idx]["name"],
                        "numero_semana": int(wk.split("_")[-1]),
                        "dia_semana":   int(dy.split("_")[-1]),
                        "ordem_visita": o
                    })
        if rows:
            df = pd.DataFrame(rows)
            df["cod"] = df["cod"].astype(str)
            df = df[["cod","numero_semana","dia_semana","ordem_visita"]]
            csv_b = df.to_csv(index=False, sep=";").encode("utf-8")
            st.sidebar.download_button(
                "📥 Baixar CSV com Rotas IA",
                data=csv_b,
                file_name="rotas_IA_otimizadas.csv",
                mime="text/csv",
                key="csv_ia"
            )

# 11) Desenha apenas o dia/semana selecionados no mapa

m = folium.Map(
    location=[placemarks[mostrar_idxs[0]]["lat"], placemarks[mostrar_idxs[0]]["lon"]],
    zoom_start=14
)

# 11.1) rota via ORS-directions (ou linha reta)
coords = [(placemarks[i]["lon"], placemarks[i]["lat"]) for i in mostrar_idxs]

fg_route = folium.FeatureGroup(name=f"Rota {sem_sel}/{dia_sel}", show=True)
if ors_client and len(coords) > 1:
    try:
        gj = get_route_geojson(tuple(coords))
        folium.GeoJson(
            gj,
            style_function=lambda feat: {"color":"blue","weight":4,"opacity":0.7}
        ).add_to(fg_route)
    except:
        folium.PolyLine(
            [(lat,lon) for lon,lat in coords],
            color="blue", weight=4, opacity=0.7
        ).add_to(fg_route)
else:
    folium.PolyLine(
        [(lat,lon) for lon,lat in coords],
        color="blue", weight=4, opacity=0.7
    ).add_to(fg_route)
fg_route.add_to(m)

# 11.2) marcadores DO DIA ATIVO
for seq, idx in enumerate(mostrar_idxs, start=1):
    p = placemarks[idx]
    fg = folium.FeatureGroup(
        name=f"{seq:02d} – {p['name']}",
        show=True
    )
    folium.Marker(
        [p["lat"], p["lon"]],
        popup=f"{seq:02d} – {p['name']}",
        icon=folium.Icon(color="red", icon="info-sign")
    ).add_to(fg)
    fg.add_to(m)

# marcador central
p0 = placemarks[mostrar_idxs[0]]
folium.CircleMarker(
    [p0["lat"], p0["lon"]],
    radius=8, color="yellow",
    fill=True, fill_color="yellow", fill_opacity=0.8
).add_to(m)

folium.LayerControl(collapsed=False).add_to(m)
folium_static(m, width=1200, height=700)

# 12) Salvar KML ajustado
def build_kml(pts, idxs):
    k   = ET.Element("kml", xmlns=NS["k"])
    d   = ET.SubElement(k, "Document")
    ET.SubElement(d, "name").text = f"Roteiro {sem_sel}/{dia_sel} (ajustado)"
    wkf = ET.SubElement(d, "Folder"); ET.SubElement(wkf, "name").text = sem_sel
    dyf = ET.SubElement(wkf, "Folder"); ET.SubElement(dyf, "name").text = dia_sel
    for s, i in enumerate(idxs, start=1):
        p  = pts[i]
        pm = ET.SubElement(dyf, "Placemark"); ET.SubElement(pm, "name").text = p["name"]
        pt = ET.SubElement(pm, "Point"); ET.SubElement(pt, "coordinates").text = f"{p['lon']},{p['lat']},0"
    buf = io.BytesIO()
    ET.ElementTree(k).write(buf, encoding="utf-8", xml_declaration=True)
    return buf.getvalue()

st.sidebar.markdown("---")
if st.sidebar.button("💾 Salvar KML Ajustado"):
    kb = build_kml(placemarks, mostrar_idxs)
    st.sidebar.download_button(
        "📥 Baixar KML",
        data=kb,
        file_name=f"rota_{sem_sel}_{dia_sel}.kml",
        mime="application/vnd.google-earth.kml+xml",
        key="kml_download"
    )
