"""
A · Infraestructura

Que el sistema este desplegado como dice el docker-compose.yml y que la
unica puerta hacia afuera sea el gateway (RNF-03).

Los puertos se prueban DESDE WINDOWS: ejecutar.ps1 los revisa antes de
lanzar el contenedor de pruebas y pasa el resultado en PUERTOS_WINDOWS.
Probarlos desde dentro de la red de Docker no demostraria nada, porque
ahi los microservicios SI deben responder.
"""

import os
import socket

import httpx

from apoyo.docker import CONTENEDORES

LETRA = "A"
TITULO = "Infraestructura"
DESCRIPCION = "Contenedores, salud de MySQL y puertos visibles desde la máquina."

MICROSERVICIOS = {
    "8081": ("ms-solicitudes", "asilo-ms-solicitudes"),
    "8082": ("ms-cobros", "asilo-ms-cobros"),
    "8083": ("ms-pacientes", "asilo-ms-pacientes"),
}


def puertos_desde_windows() -> tuple[dict[str, str], str]:
    """
    Devuelve {puerto: estado} y de donde salio el dato.

    Si el script se corrio sin ejecutar.ps1, se prueba contra la maquina
    anfitriona por host.docker.internal, que en Docker Desktop apunta a
    Windows, y el reporte lo aclara.
    """
    texto = os.getenv("PUERTOS_WINDOWS", "").strip()
    if texto:
        resultado = {}
        for par in texto.split(";"):
            puerto, _, estado = par.partition("=")
            resultado[puerto] = estado
        return resultado, "probado desde Windows"

    resultado = {}
    for puerto in ("8080", "8081", "8082", "8083"):
        try:
            with socket.create_connection(("host.docker.internal", int(puerto)), timeout=2):
                resultado[puerto] = "abierto"
        except OSError:
            resultado[puerto] = "cerrado"
    return resultado, "probado contra host.docker.internal"


def ejecutar(ctx) -> None:
    rep, docker = ctx.rep, ctx.docker
    puertos, origen = puertos_desde_windows()

    with rep.caso(
        "Los siete contenedores del sistema están en ejecución",
        "RNF-22 (despliegue completo con un solo comando)",
        "Los 7 contenedores del docker-compose en estado «running»",
    ) as c:
        estados = {n: docker.estado(n) for n in CONTENEDORES}
        c.obtenido = ", ".join(f"{n.removeprefix('asilo-')}: {e}" for n, e in estados.items())
        c.pasa = all(e == "running" for e in estados.values())

    with rep.caso(
        "MySQL reporta estado saludable",
        "Infraestructura (healthcheck de MySQL en el compose)",
        "Healthcheck de asilo-mysql en «healthy»",
    ) as c:
        salud = docker.salud("asilo-mysql")
        version = ctx.root.uno("SELECT VERSION()")
        c.obtenido = f"healthcheck «{salud}» · MySQL {version} acepta conexiones"
        c.pasa = salud == "healthy"

    with rep.caso(
        "El gateway responde en el puerto 8080",
        "RNF-03 (el gateway es la única puerta)",
        "Puerto 8080 abierto desde la máquina y la pantalla de ingreso responde 200",
    ) as c:
        estado = puertos.get("8080", "sin dato")
        abierto, _, http = estado.partition(":")
        c.obtenido = f"8080 {abierto} ({origen})" + (f" · GET / → {http}" if http else "")
        c.pasa = abierto == "abierto" and (http in ("", "200"))

    with rep.caso(
        "Los microservicios no responden en 8081, 8082 ni 8083 desde fuera",
        "RNF-03",
        "Los tres puertos cerrados desde la máquina, ningún microservicio publica "
        "puertos, y aun así los tres responden dentro de la red interna",
    ) as c:
        lineas, todo_bien = [], True
        for puerto, (servicio, contenedor) in MICROSERVICIOS.items():
            afuera = puertos.get(puerto, "sin dato")
            publicados = docker.puertos_publicados(contenedor)
            # La contraprueba: si el servicio estuviera caido, el puerto
            # tambien se veria cerrado y la prueba pasaria por la razon
            # equivocada. Tiene que estar cerrado Y vivo.
            try:
                interno = httpx.get(f"http://{servicio}:{puerto}/health", timeout=5).status_code
            except httpx.HTTPError as error:
                interno = f"sin respuesta ({type(error).__name__})"
            lineas.append(
                f"{puerto} ({servicio}): {afuera} desde fuera · "
                f"puertos publicados: {list(publicados) or 'ninguno'} · /health interno: {interno}"
            )
            todo_bien &= afuera == "cerrado" and not publicados and interno == 200
        c.obtenido = "\n".join(lineas) + f"\n({origen})"
        c.pasa = todo_bien
