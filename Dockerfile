FROM python:3.11.9

WORKDIR /app

RUN apt-get update && \
    apt-get install -y build-essential python3-dev && \
    rm -rf /var/lib/apt/lists/*

COPY . /app

RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

EXPOSE 8501

CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]