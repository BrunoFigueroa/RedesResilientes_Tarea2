FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY mapa.py .
EXPOSE 8080
CMD ["sh", "-c", "python -u mapa.py && echo '[web] Mapa en http://localhost:8080' && exec python -m http.server 8080 --directory /output"]
