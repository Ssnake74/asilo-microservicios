"""
Gateway del Sistema del Asilo de Ancianos "Cabeza de Algodon"

Unica entrada del sistema (puerto 8080): sirve las pantallas, abre la
sesion, bloquea tras varios intentos fallidos, revisa el permiso del
rol, reenvia al microservicio y anota en la bitacora. Los microservicios
no conocen los usuarios ni los roles.
"""

import os
from contextlib import asynccontextmanager

import httpx
from fastapi import Cookie, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import db
from .schemas import Credenciales
from .seguridad import (
    ADMIN,
    NOMBRE_ROL,
    RUTAS,
    SERVICIOS,
    nuevo_token,
    puede,
    recursos_gestionables,
    recursos_visibles,
    ruta_sospechosa,
    verificar_contrasena,
)

PUBLICO = "/code/publico"
TIEMPO_LIMITE = 8.0

# En produccion el sitio va por HTTPS y la cookie de sesion solo viaja
# cifrada. En desarrollo (http://localhost) queda apagado.
COOKIE_SEGURA = os.getenv("COOKIE_SEGURA") == "1"

# El mismo texto para un recurso que no existe y para una ruta armada a
# mano que se rechaza: quien la intenta no debe poder distinguirlos.
RECURSO_INEXISTENTE = "Ese recurso no existe en el sistema."


@asynccontextmanager
async def ciclo_de_vida(app: FastAPI):
    db.init_db()
    # Un solo cliente HTTP para todos los reenvios: abrir una conexion por
    # peticion seria lento y desperdiciaria sockets.
    app.state.cliente = httpx.AsyncClient(timeout=TIEMPO_LIMITE)
    yield
    await app.state.cliente.aclose()


app = FastAPI(
    title="Gateway - Asilo Cabeza de Algodon",
    description="Puerta unica del sistema: autenticacion, permisos y reenvio.",
    version="1.0.0",
    lifespan=ciclo_de_vida,
)

# Sin CORSMiddleware a proposito: pantallas y API salen del mismo origen.


# =====================================================================
# Bitacora de auditoria
#
# Se anota en el gateway porque es el unico punto por el que pasa todo.
#
#   SI  POST, PUT, PATCH y DELETE  -> cambian datos
#   SI  cualquier rechazo 401 o 403, aunque sea un GET
#   NO  los GET que salen bien     -> llenarian la tabla sin aportar nada
#
# Nunca se guarda el cuerpo de la peticion.
# =====================================================================

METODOS_QUE_MODIFICAN = {"POST", "PUT", "PATCH", "DELETE"}
CODIGOS_RECHAZO = {401, 403}


def direccion_de_origen(request: Request) -> str:
    """
    De donde vino la peticion.

    Detras de Docker suele ser la direccion de la red interna (algo como
    172.18.0.1), la misma para todos. Por eso el bloqueo de ingresos se
    cuenta por usuario y no por IP: por IP bloquearia a todo el asilo.
    """
    return request.client.host if request.client else "desconocido"


def anotar(request: Request, usuario: str | None, rol: str | None, codigo: int,
           siempre: bool = False) -> None:
    """
    Escribe una linea en la bitacora, si corresponde anotarla.

    'siempre' salta esa regla, para rechazos que no son 401 ni 403 y hay
    que conservar: el 404 a una ruta armada a mano para escalar permisos.

    Va en un try: si la bitacora falla, la operacion del usuario no se
    cae. El fallo queda en el log del contenedor.
    """
    metodo = request.method.upper()
    if not siempre and metodo not in METODOS_QUE_MODIFICAN and codigo not in CODIGOS_RECHAZO:
        return
    try:
        db.registrar_en_bitacora(
            usuario=usuario,
            rol=rol,
            metodo=metodo,
            # La ruta sin la consulta: en un "?buscar=..." podria ir el
            # nombre de un interno.
            recurso=request.url.path,
            codigo=codigo,
            origen=direccion_de_origen(request),
        )
    except Exception as error:
        print(f"[gateway] No se pudo escribir en la bitacora: {error}", flush=True)


# =====================================================================
# Sesion
# =====================================================================

def sesion_actual(token: str | None) -> dict:
    """Devuelve el usuario de la sesion o corta con 401."""
    if not token:
        raise HTTPException(status_code=401, detail="Debe iniciar sesión.")
    usuario = db.usuario_de_sesion(token)
    if usuario is None:
        raise HTTPException(status_code=401, detail="Su sesión venció. Vuelva a entrar.")
    return usuario


@app.post("/api/login", tags=["Sesion"])
def login(datos: Credenciales, request: Request, response: Response):
    """
    Valida usuario y contrasena y abre una sesion.

    El mensaje de error es el mismo exista o no el usuario: distinguirlos
    le confirmaria a un atacante cuales nombres son validos.

    Antes se comprueba el bloqueo: cinco fallos en quince minutos cierran
    el ingreso. PBKDF2 hace lento cada intento, pero sin bloqueo se
    podrian probar contrasenas sin limite.
    """
    usuario = datos.usuario.strip().lower()
    origen = direccion_de_origen(request)

    # El bloqueo va primero: un usuario bloqueado no llega a comprobar la
    # contrasena, que es la parte cara.
    minutos = db.minutos_de_bloqueo(usuario)
    if minutos > 0:
        # 429, con el mismo mensaje exista o no el usuario: que unos se
        # bloquearan y otros no delataria los nombres validos.
        detalle = (
            "Por seguridad, el ingreso quedó bloqueado tras varios intentos fallidos. "
            f"Vuelva a intentar en {minutos} minuto{'s' if minutos != 1 else ''}."
        )
        anotar(request, None, None, 429)
        raise HTTPException(status_code=429, detail=detalle)

    fila = db.buscar_usuario(usuario)

    if fila is None or not verificar_contrasena(datos.contrasena, fila["contrasena"]):
        # Se anota el fallo aunque el usuario no exista.
        db.registrar_intento_fallido(usuario, origen)
        anotar(request, None, None, 401)
        raise HTTPException(status_code=401, detail="Usuario o contraseña incorrectos.")

    db.limpiar_intentos(usuario)

    token = nuevo_token()
    db.abrir_sesion(token, fila["id"])
    anotar(request, fila["usuario"], fila["rol"], 200)

    # httponly: un script inyectado no puede leer la sesion. lax: la
    # cookie no viaja en peticiones desde otros sitios.
    response.set_cookie(
        key="sesion", value=token, httponly=True, samesite="lax",
        secure=COOKIE_SEGURA, path="/",
    )

    return {
        "usuario": fila["usuario"],
        "nombre": fila["nombre"],
        "rol": fila["rol"],
        "rol_nombre": NOMBRE_ROL.get(fila["rol"], fila["rol"]),
        "recursos": recursos_visibles(fila["rol"]),
        "gestiona": recursos_gestionables(fila["rol"]),
    }


@app.post("/api/logout", tags=["Sesion"])
def logout(request: Request, response: Response, sesion: str | None = Cookie(default=None)):
    """Cierra la sesion borrando la fila de la base y la cookie."""
    # Quien era se averigua antes de borrar la sesion, o la bitacora
    # anotaria la salida de "nadie".
    quien = db.usuario_de_sesion(sesion) if sesion else None
    if sesion:
        db.cerrar_sesion(sesion)
    response.delete_cookie("sesion", path="/")
    anotar(request, quien["usuario"] if quien else None,
           quien["rol"] if quien else None, 200)
    return {"mensaje": "Sesión cerrada."}


@app.get("/api/yo", tags=["Sesion"])
def quien_soy(sesion: str | None = Cookie(default=None)):
    """Lo consulta el panel al cargar, para saber a quien mostrarle que."""
    usuario = sesion_actual(sesion)
    return {
        "usuario": usuario["usuario"],
        "nombre": usuario["nombre"],
        "rol": usuario["rol"],
        "rol_nombre": NOMBRE_ROL.get(usuario["rol"], usuario["rol"]),
        "recursos": recursos_visibles(usuario["rol"]),
        "gestiona": recursos_gestionables(usuario["rol"]),
    }


# =====================================================================
# Tablero de estado
# =====================================================================

@app.get("/api/salud", tags=["Estado"])
async def salud(sesion: str | None = Cookie(default=None)):
    """
    Pregunta el /health de cada microservicio y junta las respuestas.

    Cada consulta va en su propio try: un servicio caido se marca abajo
    sin tumbar el tablero completo.
    """
    sesion_actual(sesion)
    resultado = {}
    for nombre, url in SERVICIOS.items():
        try:
            respuesta = await app.state.cliente.get(f"{url}/health", timeout=3.0)
            respuesta.raise_for_status()
            resultado[nombre] = {"arriba": True, "detalle": respuesta.json()}
        except Exception:
            resultado[nombre] = {"arriba": False, "detalle": None}
    return resultado


# =====================================================================
# Consulta de la bitacora
#
# Va antes del reenvio: FastAPI revisa las rutas en orden, y
# /api/{recurso} se tragaria /api/bitacora si estuviera primero.
# =====================================================================

@app.get("/api/bitacora", tags=["Auditoria"])
def ver_bitacora(
    request: Request,
    sesion: str | None = Cookie(default=None),
    usuario: str | None = Query(default=None, description="Filtra por nombre de usuario"),
    desde: str | None = Query(default=None, description="Fecha inicial, AAAA-MM-DD"),
    hasta: str | None = Query(default=None, description="Fecha final, AAAA-MM-DD"),
    limite: int = Query(default=200, ge=1, le=db.LIMITE_BITACORA),
):
    """
    Devuelve la bitacora. Solo para el rol ADMIN.

    El rol se revisa aqui a mano y no con PERMISOS porque la bitacora
    vive en el gateway y no se reenvia. Es la unica excepcion.

    403 y no 404: quien no es administrador debe saber que existe y que
    no le corresponde.
    """
    try:
        quien = sesion_actual(sesion)
    except HTTPException as fallo:
        anotar(request, None, None, fallo.status_code)
        raise

    if quien["rol"] != ADMIN:
        anotar(request, quien["usuario"], quien["rol"], 403)
        raise HTTPException(
            status_code=403,
            detail="Solo el administrador del sistema puede consultar la bitácora.",
        )

    return db.consultar_bitacora(usuario=usuario, desde=desde, hasta=hasta, limite=limite)


# =====================================================================
# Reenvio a los microservicios
# =====================================================================

@app.api_route(
    "/api/{recurso}{resto:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    tags=["Reenvio"],
)
async def reenviar(recurso: str, resto: str, request: Request,
                   sesion: str | None = Cookie(default=None)):
    """
    Toma /api/tarifas/3 y lo manda a http://ms-cobros:8082/tarifas/3.

    El orden importa: primero quien es (401), luego que la ruta no se
    salga de su recurso (404), luego si puede (403), y solo entonces se
    reenvia. Una peticion sin permiso nunca llega al microservicio.
    """
    # Sin sesion no se sabe quien es: se anota como intento anonimo.
    try:
        usuario = sesion_actual(sesion)
    except HTTPException as fallo:
        anotar(request, None, None, fallo.status_code)
        raise

    # Va antes del permiso: el permiso se decide con el primer tramo, y con
    # un ".." en el resto se aprobaria un recurso y se reenviaria otro.
    #
    # 404 y no 403: un 403 le confirmaria a quien lo intenta que esa ruta
    # lleva a alguna parte.
    if ruta_sospechosa(resto):
        anotar(request, usuario["usuario"], usuario["rol"], 404, siempre=True)
        raise HTTPException(status_code=404, detail=RECURSO_INEXISTENTE)

    if recurso not in RUTAS:
        raise HTTPException(status_code=404, detail=RECURSO_INEXISTENTE)

    if not puede(usuario["rol"], recurso, request.method):
        # El caso que mas importa registrar: alguien con sesion valida
        # intentando algo que no le corresponde.
        anotar(request, usuario["usuario"], usuario["rol"], 403)
        raise HTTPException(
            status_code=403,
            detail=(
                f"Su rol ({NOMBRE_ROL.get(usuario['rol'], usuario['rol'])}) "
                f"no tiene permiso para esta acción."
            ),
        )

    base, prefijo = RUTAS[recurso]
    destino = f"{base}{prefijo}{resto}"

    try:
        respuesta = await app.state.cliente.request(
            method=request.method,
            url=destino,
            params=request.query_params,
            content=await request.body(),
            headers={"content-type": request.headers.get("content-type", "application/json")},
        )
    except httpx.RequestError:
        # 503: el servicio de atras no responde. Se anota igual, como
        # operacion intentada que no se pudo completar.
        anotar(request, usuario["usuario"], usuario["rol"], 503)
        raise HTTPException(
            status_code=503,
            detail=f"El servicio de {recurso} no está disponible en este momento.",
        )

    # Se anota despues de la respuesta para guardar el codigo real: un
    # borrado que ocurrio (204) no es uno rechazado (409 o 422).
    anotar(request, usuario["usuario"], usuario["rol"], respuesta.status_code)

    # 204 (borrado) no trae cuerpo: devolverlo con json() reventaria.
    if respuesta.status_code == 204:
        return Response(status_code=204)

    return JSONResponse(status_code=respuesta.status_code, content=respuesta.json())


# =====================================================================
# Pantallas
#
# Van al final: FastAPI revisa las rutas en orden, y el montaje de
# archivos se tragaria las de /api si estuviera arriba.
# =====================================================================

@app.get("/", include_in_schema=False)
def pantalla_login():
    return FileResponse(f"{PUBLICO}/login.html")


@app.get("/panel", include_in_schema=False)
def pantalla_panel():
    return FileResponse(f"{PUBLICO}/panel.html")


app.mount("/", StaticFiles(directory=PUBLICO), name="publico")
