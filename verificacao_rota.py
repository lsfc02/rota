import os
import math
import json
import time
from dotenv import load_dotenv
import openrouteservice
from openrouteservice.exceptions import ApiError
from langchain_groq import ChatGroq

# Carrega configuração
load_dotenv()
ORS_API_KEY       = os.getenv("ORS_API_KEY")
GROQ_API_KEY      = os.getenv("GROQ_API_KEY")
MAX_JUMP_KM       = float(os.getenv("MAX_JUMP_KM", 100))
MAX_TIME_DIFF_MIN = float(os.getenv("MAX_DIFF_MIN", 30))
WORKING_SPEED_KMH = float(os.getenv("SPEED_KMH", 40))
REQUEST_DELAY_SEC = float(os.getenv("ORS_DELAY_SEC", 2))
MAX_RETRIES       = int(os.getenv("ORS_MAX_RETRIES", 5))
ORS_ENABLED       = os.getenv("ORS_ENABLED", "true").lower() == "true"

class RouteVerifier:
    def __init__(self):
        # Cliente ORS opcional
        self.ors = openrouteservice.Client(key=ORS_API_KEY) if (ORS_API_KEY and ORS_ENABLED) else None
        self.cache = {}  # cache para amostras ORS
        # LLM Groq
        self.llm = ChatGroq(
            groq_api_key=GROQ_API_KEY,
            model_name="llama3-8b-8192",
            temperature=0.0
        )

    @staticmethod
    def haversine(a, b):
        """Distância em km entre dois pares (lat, lon)."""
        R = 6371
        φ1, φ2 = math.radians(a[0]), math.radians(b[0])
        dφ = math.radians(b[0] - a[0])
        dλ = math.radians(b[1] - a[1])
        h = math.sin(dφ/2)**2 + math.cos(φ1)*math.cos(φ2)*math.sin(dλ/2)**2
        return R * 2 * math.atan2(math.sqrt(h), math.sqrt(1-h))

    def get_sample_duration(self, dia, visitas):
        """Consulta ORS apenas para o primeiro par de visitas no dia."""
        if not self.ors or len(visitas) < 2:
            return None
        key = f"sample_{dia}"
        if key in self.cache:
            return self.cache[key]
        v1, v2 = visitas[0], visitas[1]
        c1 = [v1['longitude'], v1['latitude']]
        c2 = [v2['longitude'], v2['latitude']]
        for attempt in range(1, MAX_RETRIES+1):
            try:
                mat = self.ors.distance_matrix(
                    locations=[c1, c2], metrics=["duration"],
                    sources=[0], destinations=[1]
                )
                sec = mat['durations'][0][0]
                self.cache[key] = sec
                time.sleep(REQUEST_DELAY_SEC)
                return sec
            except ApiError as e:
                if attempt == MAX_RETRIES:
                    print(f"Erro ORS amostra dia {dia}: {e}")
                    return None
                time.sleep(REQUEST_DELAY_SEC * attempt)
        return None

    def verify(self, rota):
        issues = []
        for day in rota:
            visitas = day.get('visitas', [])
            # calcula amostra ORS
            sample_sec = self.get_sample_duration(day['dia'], visitas)
            for i in range(len(visitas) - 1):
                v1, v2 = visitas[i], visitas[i+1]
                c1 = (v1['latitude'], v1['longitude'])
                c2 = (v2['latitude'], v2['longitude'])
                # 1) Haversine
                dist_km = self.haversine(c1, c2)
                if dist_km > MAX_JUMP_KM:
                    issues.append(
                        f"Dia {day['dia']}: salto de {dist_km:.1f} km entre {v1['id']} → {v2['id']}"
                    )
                    continue
                # 2) ORS sample
                if sample_sec is not None and i == 0:
                    min_ors = sample_sec / 60
                    min_hav = dist_km / WORKING_SPEED_KMH * 60
                    diff = abs(min_ors - min_hav)
                    if diff > MAX_TIME_DIFF_MIN:
                        issues.append(
                            f"Dia {day['dia']}: tempo ORS {min_ors:.1f} min vs haversine {min_hav:.1f} min"
                        )
        if not issues:
            return "✅ Rota validada sem inconsistências detectadas."
        # resumo e LLM
        summary = "\n".join(issues)
        system = (
            "Você é um assistente especialista em verificação de rotas. "
            "Explique possíveis causas para cada item abaixo e sugira correções." 
        )
        resp = self.llm.create(messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": f"Problemas detectados:\n{summary}"}
        ])
        return resp.choices[0].message.content

if __name__ == '__main__':
    rota = json.load(open('rota.json','r',encoding='utf-8'))
    verifier = RouteVerifier()
    feedback = verifier.verify(rota)
    print("\n🔍 Feedback de verificação:\n", feedback)
