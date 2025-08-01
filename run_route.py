import sys
import os
import json
import math
import pandas as pd
from typing import List, Dict, Tuple
from collections import defaultdict
from dotenv import load_dotenv

from openrouteservice import Client as ORSClient
from openrouteservice.optimization import Job, Vehicle

load_dotenv()

def gerar_rota(path_csv: str, num_semanas: int = 2) -> Tuple[pd.DataFrame, List[Dict], Dict]:
    # 1) Carrega e filtra CSV
    df = pd.read_csv(path_csv)
    df["clilatitude"]  = pd.to_numeric(df["clilatitude"], errors="coerce")
    df["clilongitude"] = pd.to_numeric(df["clilongitude"], errors="coerce")
    df = df.dropna(subset=["codcli","clilatitude","clilongitude", "nomcli"])
    df = df[(df.clilatitude != 0) & (df.clilongitude != 0)]

    # 2) Lista de clientes
    clientes = [
        {
            "cod_cliente": str(int(r.codcli)),
            "nome": str(r.nomcli).strip(),
            "latitude": float(r.clilatitude),
            "longitude": float(r.clilongitude)
        }
        for _, r in df.iterrows()
    ]
    n = len(clientes)

    # 3) Rota global via Haversine + Nearest Neighbor
    def hav(a, b):
        R = 6371
        φ1, φ2 = math.radians(a[0]), math.radians(b[0])
        dφ = math.radians(b[0] - a[0])
        dλ = math.radians(b[1] - a[1])
        h = math.sin(dφ/2)**2 + math.cos(φ1)*math.cos(φ2)*math.sin(dλ/2)**2
        return R * 2 * math.atan2(math.sqrt(h), math.sqrt(1-h))

    mat = [[0.0]*n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if i != j:
                a = (clientes[i]["latitude"], clientes[i]["longitude"])
                b = (clientes[j]["latitude"], clientes[j]["longitude"])
                mat[i][j] = hav(a, b)/40*60

    unv = set(range(1, n))
    route = [0]
    cur = 0
    while unv:
        nxt = min(unv, key=lambda j: mat[cur][j])
        unv.remove(nxt); route.append(nxt); cur = nxt

    # 4) Fatiamento em dias úteis baseado nas semanas escolhidas
    dias_uteis = num_semanas * 5  # 5 dias úteis por semana
    por_dia = math.ceil(len(route)/dias_uteis)
    slices = [route[i*por_dia:(i+1)*por_dia] for i in range(dias_uteis)]

    # 5) Chama ORS Optimization por dia (cada fatia ≤70)
    ors = ORSClient(key=os.getenv("ORS_API_KEY"))
    weekdays = ["Segunda-feira","Terça-feira","Quarta-feira","Quinta-feira","Sexta-feira"]

    rota_json: List[Dict] = []
    agenda = defaultdict(dict)
    df_rows = []

    for vid, day in enumerate(slices, start=1):
        visitas = []
        if day:
            # criar jobs
            jobs = [
                Job(
                    id=client_idx+1,
                    service=300,
                    amount=[1],
                    location=(clientes[client_idx]["longitude"], clientes[client_idx]["latitude"])
                )
                for client_idx in day
            ]
            # veículo único
            depot = (clientes[day[0]]["longitude"], clientes[day[0]]["latitude"])
            vehicle = Vehicle(
                id=vid,
                profile="driving-car",
                start=depot,
                end=depot,
                capacity=[len(jobs)],
                time_window=[0, 14*24*3600]
            )

            res = ors.optimization(jobs=jobs, vehicles=[vehicle])

            # Extrai lista de job-ids dos steps (type=="job")
            steps = res["routes"][0].get("steps", [])
            job_steps = [s for s in steps if s.get("type") == "job"]
            route_jobs = [s["job"] for s in job_steps]

            # Monta visitas na ordem exata
            for ordem, job_id in enumerate(route_jobs, start=1):
                client_idx = job_id - 1
                c = clientes[client_idx]
                visitas.append({
                    "id": c["cod_cliente"],
                    "nome": c["nome"],
                    "latitude": c["latitude"],
                    "longitude": c["longitude"]
                })
                semana = ((vid - 1) // 5) + 1
                dia_sem = (vid - 1) % 5 + 1
                df_rows.append({
                    "cod": c["cod_cliente"],
                    "numero_semana": semana,
                    "dia_semana": dia_sem,
                    "ordem_visita": ordem
                })

        rota_json.append({"dia": vid, "visitas": visitas})

        if day:
            semana = ((vid - 1) // 5) + 1
            dia_label = weekdays[(vid - 1) % 5]
            agenda[f"Semana {semana}"][dia_label] = [f"{v['id']} - {v['nome']}" for v in visitas]  # pode ser só v['id'] se preferir

    full_json = {"clientes": clientes, "agenda": dict(agenda)}
    df_rota = pd.DataFrame(df_rows, columns=["cod","numero_semana","dia_semana","ordem_visita"])
    return df_rota, rota_json, full_json


if __name__ == "__main__":
    if len(sys.argv) not in [2, 3]:
        print("Uso: python run_route.py caminho/para/arquivo.csv [num_semanas]")
        sys.exit(1)

    path_csv = sys.argv[1]
    num_semanas = int(sys.argv[2]) if len(sys.argv) == 3 else 2

    df_rota, rota_json, full_json = gerar_rota(path_csv, num_semanas=num_semanas)
    print(df_rota.head(), f"\n✅ Processados: {len(df_rota)} registros.")
    with open("rota.json","w",encoding="utf-8") as f:
        json.dump(rota_json, f, ensure_ascii=False, indent=2)
    with open("agenda_full.json","w",encoding="utf-8") as f:
        json.dump(full_json, f, ensure_ascii=False, indent=2)
