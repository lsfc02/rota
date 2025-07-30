import pandas as pd
from langchain.schema import Document

def excel_para_docs(caminho: str) -> list[Document]:
    
    df = pd.read_csv(caminho)

    docs: list[Document] = []
    for _, row in df.iterrows():
        cod = row["codcli"]
        lat = row["clilatitude"]
        lon = row["clilongitude"]

        if pd.isna(cod) or pd.isna(lat) or pd.isna(lon):
            continue

        if lat == 0 and lon == 0:
            continue

        texto = (
            f"Cliente: {cod}\n"
            f"Latitude: {lat}\n"
            f"Longitude: {lon}\n"
        )
        metadata = {
            "cod_cliente": str(cod).strip(),
            "latitude": float(lat),
            "longitude": float(lon),
        }
        docs.append(Document(page_content=texto, metadata=metadata))

    return docs


if __name__ == "__main__":
    caminho = "data/roteiro.csv"  
    docs = excel_para_docs(caminho)
    print(f"✅ Gerados {len(docs)} documentos em memória\n")
    if docs:
        print("Exemplo de conteúdo:\n", docs[0].page_content)
