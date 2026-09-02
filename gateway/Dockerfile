FROM python:3.12-slim

WORKDIR /code

ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Las pantallas NO se copian: docker-compose monta la carpeta app-base
# en /code/publico. Asi se puede editar un HTML y ver el cambio con solo
# refrescar, sin reconstruir la imagen.

EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
