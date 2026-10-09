# Imagen de un solo uso para correr las pruebas del sistema.
#
# Existe porque en Windows no hay Python instalado: todo lo que necesitan
# las pruebas vive aqui dentro. El codigo NO se copia a la imagen; se
# monta desde la carpeta pruebas/ al correr, asi que cambiar una prueba no
# obliga a reconstruir nada.
FROM python:3.12-slim

# PYTHONUNBUFFERED: que cada caso aparezca en la consola en cuanto termina,
#   y no todos juntos al final.
# PYTHONDONTWRITEBYTECODE: la carpeta pruebas/ esta montada desde el
#   repositorio; sin esto Python dejaria carpetas __pycache__ en git status.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONIOENCODING=utf-8

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

WORKDIR /pruebas
CMD ["python", "/pruebas/pruebas.py"]
