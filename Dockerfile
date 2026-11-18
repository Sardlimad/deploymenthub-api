FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY alembic.ini ./
COPY migrations ./migrations
COPY app ./app

# Los hostings gratuitos entregan el puerto en $PORT. --proxy-headers: la IP real del cliente (límite de intentos de login).
# Un solo proceso: el tiempo real (WebSockets), la cola de avisos y el límite de intentos viven en memoria.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
