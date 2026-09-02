"""
Gateway del Sistema del Asilo de Ancianos "Cabeza de Algodon"

Es la unica puerta del sistema. El navegador habla SOLO con este
servicio; los microservicios quedan detras, en la red interna de Docker.

Hace cuatro cosas:

  1. Sirve las pantallas (login y panel).
  2. Atiende el login y guarda la sesion.
  3. Revisa, en cada peticion, si el rol tiene permiso.
  4. Reenvia la peticion al microservicio que corresponde.

Con esto el sistema queda organizado en las tres capas del documento de
arquitectura: presentacion (pantallas + gateway), logica de negocio
(los microservicios) y datos (MySQL). Microservicios es como se despliega
por dentro; tres capas es como esta organizado.

Puerto: 8080
"""

from contextlib import asynccontextmanager

import httpx
from fastapi import Cookie, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import db
from .schemas import Credenciales
from .seguridad import (
    NOMBRE_ROL,
    RUTAS,
    SERVICIOS,
    nuevo_token,
    puede,
    recursos_visibles,
    verificar_contrasena,
)

PUBLICO = "/code/publico"
TIEMPO_LIMITE = 8.0


@asynccontextmanager
async def ciclo_de_vida(app: FastAPI):
    db.init_db()
    # Un solo cliente HTTP reutilizado para todos los reenvios: abrir una
    # conexion nueva por peticion seria lento y desperdiciaria sockets.
    app.state.cliente = httpx.AsyncClient(timeout=TIEMPO_LIMITE)
    yield
    await app.state.cliente.aclose()


app = FastAPI(
    title="Gateway - Asilo Cabeza de Algodon",
    description="Puerta unica del sistema: autenticacion, permisos y reenvio.",
    version="1.0.0",
    lifespan=ciclo_de_vida,
)

# Aqui NO hay CORSMiddleware, y es a proposito. Como todo sale del mismo
# origen (localhost:8080), el navegador ya no cruza de dominio y no hace
# falta permitirlo. Esa es una de las ganancias del gateway.


# =====================================================================
# Sesion
# =====================================================================

def sesion_actual(token: str | None) -> dict:
    """Devuelve el usuario de la sesion o corta con 401."""
    if not token:
        raise HTTPException(status_code=401, detail="Debe iniciar sesion.")
    usuario = db.usuario_de_sesion(token)
    if usuario is None:
        raise HTTPException(status_code=401, detail="Su sesion vencio. Vuelva a entrar.")
    return usuario


@app.post("/api/login", tags=["Sesion"])
def login(datos: Credenciales, response: Response):
    """
    Valida usuario y contrasena y abre una sesion.

    Si algo falla, el mensaje es el mismo tanto si el usuario no existe
    como si la contrasena esta mal. Decir "ese usuario no existe" le
    confirmaria a un atacante cuales nombres son validos.
    """
    fila = db.buscar_usuario(datos.usuario.strip().lower())

    if fila is None or not verificar_contrasena(datos.contrasena, fila["contrasena"]):
        raise HTTPException(status_code=401, detail="Usuario o contrasena incorrectos.")

    token = nuevo_token()
    db.abrir_sesion(token, fila["id"])

    # httponly: el JavaScript de la pagina NO puede leer esta cookie.
    # Si alguien lograra inyectar un script, no podria robarse la sesion.
    # samesite lax: la cookie no viaja en peticiones desde otros sitios.
    response.set_cookie(
        key="sesion", value=token, httponly=True, samesite="lax", path="/"
    )

    return {
        "usuario": fila["usuario"],
        "nombre": fila["nombre"],
        "rol": fila["rol"],
        "rol_nombre": NOMBRE_ROL.get(fila["rol"], fila["rol"]),
        "recursos": recursos_visibles(fila["rol"]),
    }


@app.post("/api/logout", tags=["Sesion"])
def logout(response: Response, sesion: str | None = Cookie(default=None)):
    """Cierra la sesion borrando la fila de la base y la cookie."""
    if sesion:
        db.cerrar_sesion(sesion)
    response.delete_cookie("sesion", path="/")
    return {"mensaje": "Sesion cerrada."}


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
    }


# =====================================================================
# Tablero de estado
# =====================================================================

@app.get("/api/salud", tags=["Estado"])
async def salud(sesion: str | None = Cookie(default=None)):
    """
    Pregunta el /health de cada microservicio y junta las respuestas.

    Cada consulta va en su propio try: si un servicio esta caido, se
    marca ese como abajo y los demas siguen apareciendo arriba. Un
    servicio caido no puede tumbar el tablero completo.
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

    El orden importa: primero se comprueba QUIEN es (401), luego SI PUEDE
    (403), y solo entonces se reenvia. Una peticion sin permiso nunca
    llega al microservicio.
    """
    usuario = sesion_actual(sesion)

    if recurso not in RUTAS:
        raise HTTPException(status_code=404, detail="Ese recurso no existe en el sistema.")

    if not puede(usuario["rol"], recurso, request.method):
        raise HTTPException(
            status_code=403,
            detail=(
                f"Su rol ({NOMBRE_ROL.get(usuario['rol'], usuario['rol'])}) "
                f"no tiene permiso para esta accion."
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
        # 503 = el gateway esta bien, el servicio de atras no responde.
        raise HTTPException(
            status_code=503,
            detail=f"El servicio de {recurso} no esta disponible en este momento.",
        )

    # 204 (borrado) no trae cuerpo: devolverlo con json() reventaria.
    if respuesta.status_code == 204:
        return Response(status_code=204)

    return JSONResponse(status_code=respuesta.status_code, content=respuesta.json())


# =====================================================================
# Pantallas
#
# Van al final a proposito: FastAPI revisa las rutas en orden, y si el
# montaje de archivos estuviera arriba se tragaria las de /api.
# =====================================================================

@app.get("/", include_in_schema=False)
def pantalla_login():
    return FileResponse(f"{PUBLICO}/login.html")


@app.get("/panel", include_in_schema=False)
def pantalla_panel():
    return FileResponse(f"{PUBLICO}/panel.html")


app.mount("/", StaticFiles(directory=PUBLICO), name="publico")
