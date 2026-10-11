FROM python:3.12-slim

WORKDIR /code

ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Las pantallas no se copian: docker-compose monta app-base en
# /code/publico.

EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
