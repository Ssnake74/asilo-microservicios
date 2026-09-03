# La aplicacion base es estatica: se sirve con Nginx.
#
# Se copia la carpeta completa y no archivo por archivo, para que al
# agregar una pantalla nueva no haya que acordarse de tocar esto.
# En el sistema armado las pantallas las sirve el gateway, que monta
# esta misma carpeta como volumen.
FROM nginx:alpine
COPY . /usr/share/nginx/html/
RUN rm -f /usr/share/nginx/html/Dockerfile
EXPOSE 80
