# =====================================================================
# Pruebas automatizadas del Sistema del Asilo "Cabeza de Algodon"
#
# Uso, desde la raiz del repositorio:
#
#   powershell -ExecutionPolicy Bypass -File .\pruebas\ejecutar.ps1
#
# Que hace este archivo, y por que esta escrito en PowerShell:
#
#   1. Prueba los puertos 8080 a 8083 DESDE WINDOWS. RNF-03 dice que los
#      microservicios no deben ser alcanzables "desde fuera"; probarlo
#      desde dentro de un contenedor no seria lo mismo.
#   2. Construye la imagen de pruebas (solo la primera vez tarda).
#   3. Corre las pruebas en un contenedor de un solo uso, conectado a la
#      red del compose y con acceso al socket de Docker, porque algunas
#      pruebas detienen y vuelven a levantar contenedores.
#   4. Red de seguridad: si algo quedo detenido, pausado o desconectado
#      (por ejemplo, si se corto la corrida a la mitad), lo devuelve a
#      como estaba.
#
# Devuelve 0 si todas las pruebas pasan y 1 si alguna falla.
# =====================================================================

$ErrorActionPreference = 'Continue'
# Sin esto la consola de Windows muestra mal las tildes y las comillas
# latinas del reporte, que llega en UTF-8 desde el contenedor.
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$carpeta = $PSScriptRoot
$raiz = Split-Path $carpeta -Parent
$resultado = Join-Path $carpeta 'resultado.txt'

function Escribir-Aviso([string]$texto) {
    Write-Host $texto -ForegroundColor Yellow
}

# ---------------------------------------------------------------------
# 0. Que Docker y el sistema esten arriba
# ---------------------------------------------------------------------
docker info --format '{{.ServerVersion}}' *> $null
if ($LASTEXITCODE -ne 0) {
    Escribir-Aviso 'Docker no responde. Encienda Docker Desktop y vuelva a intentar.'
    exit 2
}

# La red se averigua preguntandole al gateway en vez de escribir el nombre
# aqui: depende del nombre de la carpeta del proyecto.
$red = (docker inspect asilo-gateway --format '{{range $k, $v := .NetworkSettings.Networks}}{{$k}} {{end}}' 2>$null)
if ($LASTEXITCODE -ne 0 -or -not $red) {
    Escribir-Aviso 'El contenedor asilo-gateway no existe. Levante el sistema con: docker compose up -d'
    exit 2
}
$red = $red.Trim().Split(' ')[0]

# ---------------------------------------------------------------------
# 1. Puertos vistos desde Windows (RNF-03)
# ---------------------------------------------------------------------
function Probar-Puerto([int]$puerto) {
    $cliente = New-Object System.Net.Sockets.TcpClient
    try {
        $tarea = $cliente.ConnectAsync('127.0.0.1', $puerto)
        return ($tarea.Wait(2000) -and $cliente.Connected)
    } catch {
        return $false
    } finally {
        $cliente.Close()
    }
}

$puertos = @()
foreach ($p in 8080, 8081, 8082, 8083) {
    $estado = if (Probar-Puerto $p) { 'abierto' } else { 'cerrado' }
    if ($p -eq 8080 -and $estado -eq 'abierto') {
        try {
            $r = Invoke-WebRequest -Uri 'http://localhost:8080/' -UseBasicParsing -TimeoutSec 5
            $estado = "abierto:$($r.StatusCode)"
        } catch {
            $estado = 'abierto:sin-respuesta'
        }
    }
    $puertos += "$p=$estado"
}
# Se pasa como texto plano separado por punto y coma, sin comillas:
# PowerShell 5.1 rompe las comillas dobles al pasarselas a un programa.
$puertosTexto = $puertos -join ';'

# ---------------------------------------------------------------------
# 2. Datos del entorno para el encabezado del reporte
# ---------------------------------------------------------------------
$sistema = (Get-CimInstance Win32_OperatingSystem)
$windows = "$($sistema.Caption) $($sistema.Version)"

$codigo = 'desconocido'
$commit = (git -C $raiz rev-parse --short HEAD 2>$null)
if ($LASTEXITCODE -eq 0 -and $commit) {
    $pendientes = @(git -C $raiz status --porcelain 2>$null).Count
    if ($pendientes -gt 0) {
        $codigo = "commit $commit, con $pendientes archivo(s) sin confirmar"
    } else {
        $codigo = "commit $commit, sin cambios pendientes"
    }
}

# ---------------------------------------------------------------------
# 3. Imagen y corrida
# ---------------------------------------------------------------------
Write-Host 'Preparando la imagen de pruebas...' -ForegroundColor DarkGray
docker build -q -t asilo-pruebas $carpeta | Out-Null
if ($LASTEXITCODE -ne 0) {
    Escribir-Aviso 'No se pudo construir la imagen de pruebas (la primera vez necesita conexión a internet).'
    exit 2
}

docker run --rm `
    --network $red `
    -v /var/run/docker.sock:/var/run/docker.sock `
    -v "${carpeta}:/pruebas" `
    -v "${raiz}\infra\mysql\init:/init-sql:ro" `
    -e "PUERTOS_WINDOWS=$puertosTexto" `
    -e "ENTORNO_WINDOWS=$windows" `
    -e "CODIGO_GIT=$codigo" `
    -e "RED_COMPOSE=$red" `
    asilo-pruebas
$salida = $LASTEXITCODE

# ---------------------------------------------------------------------
# 4. Red de seguridad
#
# El script de Python ya restaura todo en su bloque finally. Esto cubre
# el caso en que el contenedor de pruebas murio sin llegar a hacerlo.
# ---------------------------------------------------------------------
$acciones = @()

$cobros = (docker inspect asilo-ms-cobros --format '{{.State.Status}}' 2>$null)
if ($cobros -and $cobros -ne 'running') {
    docker start asilo-ms-cobros | Out-Null
    $acciones += "asilo-ms-cobros estaba '$cobros' y se volvió a encender."
}

$correo = (docker inspect asilo-mailpit --format '{{.State.Status}}' 2>$null)
if ($correo -eq 'paused') {
    docker unpause asilo-mailpit | Out-Null
    $acciones += 'asilo-mailpit estaba en pausa y se reanudó.'
}
$redesCorreo = (docker inspect asilo-mailpit --format '{{range $k, $v := .NetworkSettings.Networks}}{{$k}} {{end}}' 2>$null)
if ($redesCorreo -and -not ($redesCorreo -match [regex]::Escape($red))) {
    docker network connect --alias asilo-mailpit --alias mailpit $red asilo-mailpit | Out-Null
    $acciones += 'asilo-mailpit estaba desconectado de la red y se reconectó.'
}

if ($acciones.Count -gt 0) {
    $texto = "`r`nRED DE SEGURIDAD DEL SCRIPT DE WINDOWS`r`n" + (($acciones | ForEach-Object { "  - $_" }) -join "`r`n")
    Escribir-Aviso $texto
    if (Test-Path $resultado) {
        Add-Content -Path $resultado -Value $texto -Encoding UTF8
    }
}

if ($salida -eq 0 -or $salida -eq 1) {
    Write-Host ''
    Write-Host "Reporte guardado en: $resultado" -ForegroundColor DarkGray
}
exit $salida
