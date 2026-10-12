FROM python:3.12-slim

WORKDIR /code

ENV PYTHONUNBUFFERED=1

# El contexto de construccion es la raiz del repositorio: la imagen lleva
# tambien las pantallas de app-base.
COPY gateway/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY gateway/app ./app

# En desarrollo, docker-compose monta app-base encima de esta copia para
# ver los cambios sin reconstruir.
COPY app-base ./publico

EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
