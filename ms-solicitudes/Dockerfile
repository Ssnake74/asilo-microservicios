FROM python:3.12-slim

WORKDIR /code

# Los print() salen de inmediato en "docker compose logs": asi se ven
# los reintentos de init_db() mientras espera a MySQL.
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Los datos de conexion a MySQL llegan desde docker-compose.yml.
ENV MS_COBROS_URL=http://ms-cobros:8082

EXPOSE 8081
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8081"]
