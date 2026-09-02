FROM python:3.12-slim

WORKDIR /code

# Hace que los print() salgan de inmediato en "docker compose logs"
# en vez de quedarse guardados en memoria.
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

EXPOSE 8083
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8083"]
