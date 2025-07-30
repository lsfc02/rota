import json
import csv
import io
from typing import List, Dict, Tuple

def load_json(path: str) -> List[Dict]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def generate_kml(rota: List[Dict]) -> str:
    header = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<kml xmlns="http://www.opengis.net/kml/2.2">\n'
        '  <Document>\n'
        '    <name>Roteiro de Visitas</name>\n'
    )
    footer = '  </Document>\n</kml>'

    # 1) Gera uma pasta por dia
    day_folders = []
    for day in rota:
        day_name = f"Dia_{day['dia']}"
        placemarks = []
        for v in day.get("visitas", []):
            placemarks.append(
                f"    <Placemark>\n"
                f"      <name>{v['id']}</name>\n"
                f"      <Point>\n"
                f"        <coordinates>{v['longitude']},{v['latitude']},0</coordinates>\n"
                f"      </Point>\n"
                f"    </Placemark>\n"
            )
        day_folders.append(
            f"    <Folder>\n"
            f"      <name>{day_name}</name>\n"
            + "".join(placemarks) +
            "    </Folder>\n"
        )

    # 2) Agrupa em semanas de 5 dias úteis
    WEEK_DAYS = 5
    week_folders = []
    for w in range(0, len(day_folders), WEEK_DAYS):
        semana = w // WEEK_DAYS + 1
        content = "".join(day_folders[w : w + WEEK_DAYS])
        week_folders.append(
            f"  <Folder>\n"
            f"    <name>Semana_{semana}</name>\n"
            + content +
            "  </Folder>\n"
        )

    return header + "".join(week_folders) + footer


def export_csv_to_bytes(rota: List[Dict]) -> bytes:
    buf = io.StringIO()
    writer = csv.DictWriter(
        buf,
        fieldnames=["cod", "numero_semana", "dia_semana", "ordem_visita"],
        delimiter=";"
    )
    writer.writeheader()

    WEEK_DAYS = 5
    for day in rota:
        dia = int(day["dia"])
        numero_semana = (dia - 1) // WEEK_DAYS + 1
        dia_semana = (dia - 1) % WEEK_DAYS + 1
        for idx, v in enumerate(day.get("visitas", []), start=1):
            writer.writerow({
                "cod": v["id"],
                "numero_semana": numero_semana,
                "dia_semana": dia_semana,
                "ordem_visita": idx
            })

    return buf.getvalue().encode("utf-8")


def exportar_kml_csv(rota: List[Dict]) -> Tuple[bytes, bytes]:
    """
    Retorna (kml_bytes, csv_bytes) para download,
    agrupando em semanas de 5 dias úteis.
    """
    kml_bytes = generate_kml(rota).encode("utf-8")
    csv_bytes = export_csv_to_bytes(rota)
    return kml_bytes, csv_bytes


if __name__ == "__main__":
    rota = load_json("rota.json")
    kml, csv_b = exportar_kml_csv(rota)
    with open("test.kml", "wb") as f:
        f.write(kml)
    with open("test.csv", "wb") as f:
        f.write(csv_b)
    print("✅ test.kml e test.csv criados.")
