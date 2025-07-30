FROM python:3.11.9

WORKDIR /app

# Instala git e clona o repositório
RUN apt-get update && apt-get install -y git && \
    git clone https://github.com/lsfc02/rota . && \
    pip install --no-cache-dir -r requirements.txt

CMD ["streamlit", "run", "main.py", "--server.port=8501", "--server.address=0.0.0.0"]
