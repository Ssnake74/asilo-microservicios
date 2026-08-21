# Imagen base ligera de Python
FROM python:3.12-slim

WORKDIR /code

# Se copian primero las dependencias para aprovechar la cache de Docker
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Codigo del microservicio
COPY app ./app

# Carpeta del volumen donde vive la base de datos SQLite
RUN mkdir -p /data
ENV DB_PATH=/data/cobros.db

EXPOSE 8082
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8082"]
