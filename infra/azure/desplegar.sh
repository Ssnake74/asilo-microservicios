#!/bin/bash
# Despliega o actualiza las cuatro aplicaciones en Azure y crea los esquemas
# de MySQL. Se corre en Cloud Shell (Bash):
#
#   bash asilo-microservicios/infra/azure/desplegar.sh
#
# Usa la imagen mas reciente del registro, la que publico GitHub Actions.
# Se puede repetir: lo que ya existe se actualiza.
set -uo pipefail

RG=rg-asilo
ACR=asiloae0794
CARPETA=$(dirname "$0")
SUB=$(az account show --query id -o tsv)
API="https://management.azure.com/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.App"
fallo() { echo; echo "*** FALLO en: $1. Copia todo lo de arriba y mandalo."; exit 1; }

ETIQUETA=$(az acr repository show-tags -n $ACR --repository asilo/gateway \
  --orderby time_desc --top 1 -o tsv) || fallo "leer la etiqueta de las imagenes"
echo "Imagenes del commit: ${ETIQUETA:0:7}"

read -r -s -p "Clave del administrador de MySQL: " CLAVE_ADMIN; echo
read -r -s -p "Contrasena de aplicacion de Gmail: " CLAVE_CORREO; echo

echo; echo "=== Despliegue (2 a 5 minutos)"
URL_SITIO=$(az deployment group create -g $RG -n "asilo-$(date +%Y%m%d-%H%M%S)" \
  -f "$CARPETA/asilo.bicep" \
  -p etiqueta="$ETIQUETA" claveAdmin="$CLAVE_ADMIN" claveCorreo="$CLAVE_CORREO" \
  --query properties.outputs.url.value -o tsv) || fallo "despliegue"

echo; echo "=== Esquemas y usuarios de MySQL"
az rest --method post --url "$API/jobs/job-esquemas/start?api-version=2024-03-01" -o none \
  || fallo "arrancar el trabajo de esquemas"
for i in $(seq 1 30); do
  sleep 10
  ESTADO=$(az rest --method get --url "$API/jobs/job-esquemas/executions?api-version=2024-03-01" \
    --query "value | sort_by(@, &properties.startTime) | [-1].properties.status" -o tsv)
  echo "  $ESTADO"
  [ "$ESTADO" = "Succeeded" ] && break
  [ "$ESTADO" = "Failed" ] && fallo "trabajo de esquemas"
done
[ "$ESTADO" = "Succeeded" ] || fallo "el trabajo de esquemas no termino a tiempo"

echo; echo "=== Listo"
echo "Sistema: $URL_SITIO"
