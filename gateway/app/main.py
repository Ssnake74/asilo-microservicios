"""
Gateway del Sistema del Asilo de Ancianos "Cabeza de Algodon"

Es la unica puerta del sistema. El navegador habla SOLO con este
servicio; los microservicios quedan detras, en la red interna de Docker.

Hace seis cosas:

  1. Sirve las pantallas (login y panel).
  2. Atiende el login y guarda la sesion.
  3. Bloquea el ingreso tras varios intentos fallidos.
  4. Revisa, en cada peticion, si el rol tiene permiso.
  5. Reenvia la peticion al microservicio que corresponde.
  6. Anota en la bitacora lo que cambia datos y lo que se rechaza.

Las tres ultimas solo pueden vivir aqui: los microservicios no saben
que existen los usuarios ni los roles, y desde que dejaron de publicar
sus puertos, este es el unico camino para llegar a ellos.

Con esto el sistema queda organizado en las tres capas del documento de
arquitectura: presentacion (pantallas + gateway), logica de negocio
(los microservicios) y datos (MySQL). Microservicios es como se despliega
por dentro; tres capas es como esta organizado.

Puerto: 8080
"""

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
    recursos_visibles,
    ruta_sospechosa,
    verificar_contrasena,
)

PUBLICO = "/code/publico"
TIEMPO_LIMITE = 8.0

# El mismo texto para un recurso que no existe y para una ruta armada a
# mano que se rechaza: quien la intenta no debe poder distinguirlos.
RECURSO_INEXISTENTE = "Ese recurso no existe en el sistema."


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
# Bitacora de auditoria
#
# Se anota desde aqui, en el gateway, porque es el unico punto por el
# que pasa todo: los microservicios ni siquiera saben que existen los
# usuarios y los roles.
#
# Que se anota y que no:
#
#   SI  POST, PUT, PATCH y DELETE  -> son las que cambian datos
#   SI  cualquier rechazo 401 o 403 -> aunque sea un GET; un intento de
#       entrar donde no corresponde es justo lo que hay que poder ver
#   NO  los GET que salen bien -> son miles al dia y no aportan nada,
#       solo harian la tabla imposible de leer
#
# Y nunca, en ningun caso, el cuerpo de la peticion.
# =====================================================================

METODOS_QUE_MODIFICAN = {"POST", "PUT", "PATCH", "DELETE"}
CODIGOS_RECHAZO = {401, 403}


def direccion_de_origen(request: Request) -> str:
    """
    De donde vino la peticion.

    Advertencia honesta para el video: detras de Docker esta direccion
    suele ser la de la red interna (algo como 172.18.0.1) y es la MISMA
    para todo el mundo. Sirve para dejar constancia, pero por eso el
    bloqueo de ingresos cuenta por NOMBRE DE USUARIO y no por direccion:
    contar por direccion bloquearia a todo el asilo de una vez.
    """
    return request.client.host if request.client else "desconocido"


def anotar(request: Request, usuario: str | None, rol: str | None, codigo: int,
           siempre: bool = False) -> None:
    """
    Escribe una linea en la bitacora, si corresponde anotarla.

    'siempre' salta la regla de que se anota y que no. Existe para los
    rechazos que no son 401 ni 403 pero que hay que conservar igual, como
    un intento de escalar permisos con una ruta armada a mano: ese se
    responde con 404, y aunque sea un GET es justo lo que una auditoria
    debe guardar.

    Todo va dentro de un try: si la bitacora falla, la operacion del
    usuario NO debe caerse. Una auditoria que tumba el sistema cuando se
    llena el disco es peor que no tenerla. El fallo se manda al log del
    contenedor, que es donde se revisa.
    """
    metodo = request.method.upper()
    if not siempre and metodo not in METODOS_QUE_MODIFICAN and codigo not in CODIGOS_RECHAZO:
        return
    try:
        db.registrar_en_bitacora(
            usuario=usuario,
            rol=rol,
            metodo=metodo,
            # request.url.path es la ruta sola, sin el texto de la
            # consulta: en un "?buscar=..." podria ir el nombre de un
            # interno, y eso no tiene por que quedar guardado aqui.
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

    Si algo falla, el mensaje es el mismo tanto si el usuario no existe
    como si la contrasena esta mal. Decir "ese usuario no existe" le
    confirmaria a un atacante cuales nombres son validos.

    Antes de revisar nada se comprueba el bloqueo. Cinco intentos
    fallidos en quince minutos cierran el ingreso otros quince. Sin eso,
    un programa podia probar contrasenas sin limite: las 200,000
    repeticiones de PBKDF2 hacen lento CADA intento, pero no impiden
    que se hagan millones.
    """
    usuario = datos.usuario.strip().lower()
    origen = direccion_de_origen(request)

    # El bloqueo se mira PRIMERO, antes de tocar la base de usuarios.
    # Asi un usuario bloqueado no consume ni siquiera la comprobacion
    # de la contrasena, que es la parte cara.
    minutos = db.minutos_de_bloqueo(usuario)
    if minutos > 0:
        # 429 = demasiadas peticiones. El mensaje es el mismo exista o
        # no el usuario, para no confirmar nombres validos por la via
        # de que unos se bloqueen y otros no.
        detalle = (
            "Por seguridad, el ingreso quedó bloqueado tras varios intentos fallidos. "
            f"Vuelva a intentar en {minutos} minuto{'s' if minutos != 1 else ''}."
        )
        anotar(request, None, None, 429)
        raise HTTPException(status_code=429, detail=detalle)

    fila = db.buscar_usuario(usuario)

    if fila is None or not verificar_contrasena(datos.contrasena, fila["contrasena"]):
        # Se anota el fallo INCLUSO si el usuario no existe.
        db.registrar_intento_fallido(usuario, origen)
        anotar(request, None, None, 401)
        raise HTTPException(status_code=401, detail="Usuario o contraseña incorrectos.")

    # Entro bien: se le perdonan los errores anteriores.
    db.limpiar_intentos(usuario)

    token = nuevo_token()
    db.abrir_sesion(token, fila["id"])
    anotar(request, fila["usuario"], fila["rol"], 200)

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
def logout(request: Request, response: Response, sesion: str | None = Cookie(default=None)):
    """Cierra la sesion borrando la fila de la base y la cookie."""
    # Se averigua quien era ANTES de borrar la sesion, o la bitacora
    # quedaria con la salida de "nadie".
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
# Consulta de la bitacora
#
# Va ANTES del reenvio a proposito. FastAPI revisa las rutas en el orden
# en que estan escritas, y /api/{recurso} se tragaria /api/bitacora si
# estuviera primero.
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

    La revision del rol se hace aqui a mano y no con la tabla PERMISOS
    porque la bitacora no es un recurso reenviado: vive en el propio
    gateway. Es el unico endpoint del sistema con esa excepcion.

    Se responde 403 y no 404 a proposito: quien no es administrador debe
    saber que existe y que no le corresponde, no que no existe.
    """
    try:
        quien = sesion_actual(sesion)
    except HTTPException as fallo:
        anotar(request, None, None, fallo.status_code)
        raise

    if quien["rol"] != ADMIN:
        # Un intento de leer la bitacora sin ser administrador queda,
        # el mismo, anotado en la bitacora.
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

    El orden importa: primero se comprueba QUIEN es (401), luego que la
    ruta no intente salirse de su recurso (404), luego SI PUEDE (403), y
    solo entonces se reenvia. Una peticion sin permiso nunca llega al
    microservicio.
    """
    # Sin sesion no se sabe quien es: se anota como intento anonimo.
    try:
        usuario = sesion_actual(sesion)
    except HTTPException as fallo:
        anotar(request, None, None, fallo.status_code)
        raise

    # Va ANTES de revisar el permiso, no despues: el permiso se decide con
    # el primer tramo de la ruta, y si el resto lleva un "..", lo que se
    # reenviaria es otro recurso. Revisar el permiso primero seria aprobar
    # una cosa y mandar otra.
    #
    # Se responde 404 y no 403 a proposito: un 403 le confirmaria a quien
    # lo intenta que esa ruta lleva a alguna parte. Para el, simplemente
    # no existe.
    if ruta_sospechosa(resto):
        anotar(request, usuario["usuario"], usuario["rol"], 404, siempre=True)
        raise HTTPException(status_code=404, detail=RECURSO_INEXISTENTE)

    if recurso not in RUTAS:
        raise HTTPException(status_code=404, detail=RECURSO_INEXISTENTE)

    if not puede(usuario["rol"], recurso, request.method):
        # Este es el caso que mas importa dejar registrado: alguien con
        # sesion valida intentando hacer algo que no le corresponde.
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
        # 503 = el gateway esta bien, el servicio de atras no responde.
        # Se anota igual: una operacion que se intento y no se pudo
        # completar tambien es parte de la historia del sistema.
        anotar(request, usuario["usuario"], usuario["rol"], 503)
        raise HTTPException(
            status_code=503,
            detail=f"El servicio de {recurso} no está disponible en este momento.",
        )

    # Se anota DESPUES de conocer la respuesta, para guardar el codigo
    # de verdad: no es lo mismo un borrado que ocurrio (204) que uno que
    # el microservicio rechazo (409 o 422).
    anotar(request, usuario["usuario"], usuario["rol"], respuesta.status_code)

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
