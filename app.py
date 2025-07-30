import sys
import os
import tempfile
import json

sys.path.append(os.path.dirname(__file__))

import streamlit as st
from dotenv import load_dotenv

from run_route import gerar_rota
from export_route_kmlcsv import exportar_kml_csv
from rag import RouteVerifier

import folium
from streamlit_folium import st_folium

# Carrega .env e configura página
load_dotenv()
st.set_page_config(page_title="Visualizador de Rotas", layout="wide")

# Função que cria o mapa baseado no rota_json
def build_map(rota_json):
    # encontra primeiro ponto para centralizar
    primeiro = None
    for dia in rota_json:
        if dia["visitas"]:
            primeiro = dia["visitas"][0]
            break
    if primeiro:
        m = folium.Map(location=[primeiro["latitude"], primeiro["longitude"]], zoom_start=11)
    else:
        m = folium.Map(zoom_start=2)

    cores = ["red", "blue", "green", "orange", "purple"]
    for dia in rota_json:
        idx = dia["dia"]
        coords = [(v["latitude"], v["longitude"]) for v in dia["visitas"]]
        if not coords:
            continue
        cor = cores[(idx - 1) % len(cores)]
        # desenha a linha do dia
        folium.PolyLine(coords, color=cor, weight=3, opacity=0.8).add_to(m)
        # marcadores
        for ordem, v in enumerate(dia["visitas"], start=1):
            folium.CircleMarker(
                location=(v["latitude"], v["longitude"]),
                radius=5,
                color=cor,
                fill=True,
                fill_opacity=0.7,
                popup=f"Dia {idx} • Visita {ordem}: {v['id']}"
            ).add_to(m)
    return m

# Título no topo (igual ao mapa.py)
st.title("🌐 Visualizador de Rotas")

# Sidebar para importar CSV
st.sidebar.header("🗂️ Importar CSV e gerar rota")
arquivo = st.sidebar.file_uploader("Envie seu CSV de clientes", type=["csv"])
if st.sidebar.button("Processar CSV"):
    if not arquivo:
        st.sidebar.error("Envie um arquivo primeiro.")
        st.stop()

    with st.spinner("Calculando rota…"):
        # salva CSV temporário
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".csv")
        tmp.write(arquivo.getbuffer())
        tmp.flush()
        tmp.close()

        # gera rota
        df_rota, rota_json, full_json = gerar_rota(tmp.name)

        # validação IA
        feedback = RouteVerifier().verify(rota_json)

        # gera arquivos para download
        kml_bytes, csv_bytes = exportar_kml_csv(rota_json)

    # seção de downloads
    st.success("✨ Pronto! Faça o download:")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.download_button("📥 Baixar rota.csv", csv_bytes, "rota.csv", "text/csv")
    with c2:
        st.download_button(
            "📥 Baixar rota.kml",
            kml_bytes,
            "rota.kml",
            "application/vnd.google-earth.kml+xml"
        )
    with c3:
        st.download_button(
            "📥 agenda_full.json",
            json.dumps(full_json, ensure_ascii=False, indent=2).encode("utf-8"),
            "agenda_full.json",
            "application/json"
        )

    # feedback da IA
    st.subheader("🛡️ Verificação IA")
    st.text(feedback)

    # opção de visualizar no mapa
    if st.checkbox("🔍 Visualizar rota no mapa"):
        mapa = build_map(rota_json)
        st_folium(mapa, width=800, height=500)
