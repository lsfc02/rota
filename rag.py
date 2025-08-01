import os
import math
import json
from dotenv import load_dotenv

load_dotenv()

from langchain_groq import ChatGroq
import openrouteservice

class RouteVerifier:
    def __init__(self):
        self.ors_api_key = os.getenv("ORS_API_KEY")
        self.ors = openrouteservice.Client(key=self.ors_api_key) if self.ors_api_key else None
        self.llm = ChatGroq(
            groq_api_key=os.getenv("GROQ_API_KEY"),
            model_name="llama3-8b-8192",
            temperature=0.0
        )

    @staticmethod
    def haversine(coord1, coord2):
        R = 6371
        lat1, lon1 = coord1
        lat2, lon2 = coord2
        φ1, φ2 = math.radians(lat1), math.radians(lat2)
        dφ = math.radians(lat2 - lat1)
        dλ = math.radians(lon2 - lon1)
        a = math.sin(dφ/2)**2 + math.cos(φ1)*math.cos(φ2)*math.sin(dλ/2)**2
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

    def check_sequence(self, rota):
        issues = []
        for day in rota:
            visitas = day.get('visitas', [])
            for i in range(len(visitas)-1):
                c1 = (visitas[i]['latitude'], visitas[i]['longitude'])
                c2 = (visitas[i+1]['latitude'], visitas[i+1]['longitude'])
                dist = self.haversine(c1, c2)
                if dist > 100:
                    issues.append(f"Dia {day['dia']}: salto de {dist:.1f} km entre {visitas[i]['id']} e {visitas[i+1]['id']}")
        return issues

    def verify(self, rota):
        issues = self.check_sequence(rota)

        # ORS check se disponível
        if self.ors and rota and rota[0].get('visitas', []):
            first_two = rota[0]['visitas'][:2]
            if len(first_two) == 2:
                coords = [[v['longitude'], v['latitude']] for v in first_two]
                matrix = self.ors.distance_matrix(
                    locations=coords, metrics=["duration"], sources=[0], destinations=[1]
                )
                dur = matrix["durations"][0][0]
                d_hav = self.haversine(
                    (first_two[0]['latitude'], first_two[0]['longitude']),
                    (first_two[1]['latitude'], first_two[1]['longitude'])
                ) / 40 * 60
                if abs(dur/60 - d_hav) > 30:
                    issues.append(
                        f"Inconsistência entre {first_two[0]['id']} e {first_two[1]['id']}: "
                        f"ORS {dur/60:.1f}min vs haversine {d_hav:.1f}min"
                    )

        if not issues:
            return "Rota validada sem inconsistências detectadas."

        print("👉 UTILIZANDO A IA LLM para verificar erros e sugerir correções…")

        summary = "\n".join(issues)
        system = (
            "Você é um assistente de validação de rotas. "
            "Aponte as causas dos problemas abaixo e sugira correções."
        )
        messages = [
            {"role": "system", "content": system},
            {"role": "user",   "content": f"Problemas:\n{summary}"}
        ]
        try:
            resp = self.llm.invoke(messages)
            return resp.content
        except Exception as e:
            return f"Erro LLM na verificação: {e}"

if __name__ == "__main__":
    rota = json.load(open("rota.json", "r", encoding="utf-8"))
    verifier = RouteVerifier()
    feedback = verifier.verify(rota)
    print("🔍 Feedback de verificação:\n", feedback)
