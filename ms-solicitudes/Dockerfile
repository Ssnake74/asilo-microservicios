FROM python:3.12-slim

WORKDIR /code

# Hace que los print() salgan de inmediato en "docker compose logs".
# Sin esto, los mensajes de reintento de MySQL de init_db() se quedan
# guardados en el buffer y uno no ve nada mientras el servicio espera.
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Ya no se crea /data ni se define DB_PATH: los datos viven en el
# esquema asilo_solicitudes de MySQL. Los datos de conexion llegan
# desde docker-compose.yml.
ENV MS_COBROS_URL=http://ms-cobros:8082

EXPOSE 8081
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8081"]
