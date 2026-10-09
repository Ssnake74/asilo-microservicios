"""
Seguridad y enrutamiento del Gateway.

Aqui viven cuatro cosas que no dependen ni de HTTP ni de la base de datos,
y por eso se pueden leer y probar solas:

  1. Como se guardan y verifican las contrasenas.
  2. La tabla de rutas: que microservicio atiende cada recurso.
  3. La tabla de permisos: que rol puede hacer que cosa.
  4. La deteccion de rutas que intentan salirse de su recurso.

Las dos tablas son el corazon del gateway. Estan escritas como
diccionarios a proposito: se leen de corrido y se pueden mostrar en el
video sin explicar codigo.
"""

import hashlib
import hmac
import os
import secrets
from urllib.parse import unquote

# ---------------------------------------------------------------------
# 1. Contrasenas
#
# NUNCA se guarda la contrasena. Se guarda el resultado de pasarla por
# PBKDF2, que es una funcion de un solo sentido: de la contrasena se
# llega al resultado, pero del resultado no se puede volver.
#
# La "sal" es un valor al azar distinto para cada usuario. Sirve para
# que dos personas con la misma contrasena tengan resultados distintos,
# y para que no se pueda usar una tabla de equivalencias ya calculada.
#
# Las 200,000 repeticiones existen para que probar contrasenas a la
# fuerza sea lento. Para un login legitimo son milesimas de segundo.
# ---------------------------------------------------------------------

REPETICIONES = 200_000


def cifrar_contrasena(contrasena: str, sal: str | None = None) -> str:
    """Devuelve 'sal$resumen', que es lo que se guarda en la base."""
    sal = sal or secrets.token_hex(16)
    resumen = hashlib.pbkdf2_hmac(
        "sha256", contrasena.encode("utf-8"), sal.encode("utf-8"), REPETICIONES
    ).hex()
    return f"{sal}${resumen}"


def verificar_contrasena(contrasena: str, guardado: str) -> bool:
    """
    Compara la contrasena escrita contra lo guardado.

    Se usa compare_digest y no ==, porque el == corta la comparacion en
    cuanto encuentra una diferencia. Midiendo cuanto tarda en responder,
    un atacante podria ir adivinando caracter por caracter.
    """
    try:
        sal, _ = guardado.split("$", 1)
    except ValueError:
        return False
    return hmac.compare_digest(cifrar_contrasena(contrasena, sal), guardado)


def nuevo_token() -> str:
    """Token de sesion al azar. 32 bytes es imposible de adivinar."""
    return secrets.token_urlsafe(32)


# ---------------------------------------------------------------------
# 2. Tabla de rutas
#
# El navegador solo conoce al gateway. Pide /api/pacientes y el gateway
# traduce eso a http://ms-pacientes:8083/pacientes.
#
# Se enruta por RECURSO, no por servicio, porque asi el frontend no
# necesita saber que "visitas" y "solicitudes" viven en el mismo
# contenedor. Si manana se separan, cambia esta tabla y nada mas.
# ---------------------------------------------------------------------

MS_PACIENTES = os.getenv("MS_PACIENTES_URL", "http://ms-pacientes:8083")
MS_SOLICITUDES = os.getenv("MS_SOLICITUDES_URL", "http://ms-solicitudes:8081")
MS_COBROS = os.getenv("MS_COBROS_URL", "http://ms-cobros:8082")

RUTAS: dict[str, tuple[str, str]] = {
    "pacientes":     (MS_PACIENTES,   "/pacientes"),
    "solicitudes":   (MS_SOLICITUDES, "/solicitudes"),
    "visitas":       (MS_SOLICITUDES, "/visitas"),
    "tarifas":       (MS_COBROS,      "/tarifas"),
    "cargos":        (MS_COBROS,      "/cargos"),
    "estado-cuenta": (MS_COBROS,      "/estado-cuenta"),
}

# Para el tablero de estado: nombre visible -> URL de su /health
SERVICIOS = {
    "ms-pacientes":   MS_PACIENTES,
    "ms-solicitudes": MS_SOLICITUDES,
    "ms-cobros":      MS_COBROS,
}


# ---------------------------------------------------------------------
# 3. Roles y permisos
#
# Los roles salen del enunciado del proyecto:
#
#   ADMIN          administrador del sistema, ve y hace todo
#   SECRETARIA     registra a los internos y sus familiares responsables
#   MEDICO_GENERAL evalua al interno y lo remite a una especialidad
#   FUNDACION      asigna horario y medico, y convierte la solicitud en visita
#   CAJA           tarifario, cobros y estado de cuenta de los familiares
#
# LABORATORIO y FARMACIA quedan reservados para cuando exista ms-clinico.
#
# La regla es simple: si el rol no aparece en la lista del recurso y el
# metodo, el gateway responde 403 y la peticion nunca llega al
# microservicio. Los servicios no saben que existen los roles: esa
# responsabilidad vive aqui, en un solo lugar.
# ---------------------------------------------------------------------

ADMIN = "ADMIN"
SECRETARIA = "SECRETARIA"
MEDICO_GENERAL = "MEDICO_GENERAL"
FUNDACION = "FUNDACION"
CAJA = "CAJA"

ROLES = (ADMIN, SECRETARIA, MEDICO_GENERAL, FUNDACION, CAJA)

# Nombre legible de cada rol, para mostrarlo en pantalla.
#
# Estos textos SI llevan tildes: no son identificadores del codigo, son
# lo que lee la persona en la barra de arriba de cada pantalla y en el
# mensaje cuando se le niega un permiso.
NOMBRE_ROL = {
    ADMIN: "Administrador",
    SECRETARIA: "Secretaria del asilo",
    MEDICO_GENERAL: "Médico general",
    FUNDACION: "Fundación",
    CAJA: "Caja y cobros",
}

# Casi todo el mundo necesita consultar la lista de internos, aunque
# solo la secretaria pueda modificarla.
TODOS = set(ROLES)

PERMISOS: dict[str, dict[str, set[str]]] = {
    "pacientes": {
        "GET":    TODOS,
        "POST":   {ADMIN, SECRETARIA},
        "PUT":    {ADMIN, SECRETARIA},
        "DELETE": {ADMIN},
    },
    "solicitudes": {
        # La fundacion lee las solicitudes pendientes para asignarlas,
        # pero quien las crea es el medico general.
        "GET":    {ADMIN, SECRETARIA, MEDICO_GENERAL, FUNDACION},
        "POST":   {ADMIN, MEDICO_GENERAL, FUNDACION},
        "DELETE": {ADMIN, MEDICO_GENERAL},
    },
    "visitas": {
        "GET":    {ADMIN, SECRETARIA, MEDICO_GENERAL, FUNDACION},
    },
    "tarifas": {
        # Todos ven los precios; solo caja los cambia.
        "GET":    TODOS,
        "POST":   {ADMIN, CAJA},
        "PUT":    {ADMIN, CAJA},
        "DELETE": {ADMIN, CAJA},
    },
    "cargos": {
        "GET":    {ADMIN, SECRETARIA, CAJA},
        "POST":   {ADMIN, CAJA, FUNDACION},
        "DELETE": {ADMIN, CAJA},
    },
    "estado-cuenta": {
        "GET":    {ADMIN, SECRETARIA, CAJA},
    },
}


def puede(rol: str, recurso: str, metodo: str) -> bool:
    """
    Responde si ese rol tiene permiso para ese metodo sobre ese recurso.

    Si el recurso o el metodo no estan en la tabla, la respuesta es NO.
    Se niega por omision a proposito: agregar un endpoint nuevo no debe
    quedar abierto por descuido, hay que declararlo aqui.
    """
    if recurso not in PERMISOS:
        return False
    return rol in PERMISOS[recurso].get(metodo.upper(), set())


def recursos_visibles(rol: str) -> list[str]:
    """Recursos que ese rol puede al menos consultar. Sirve para el menu."""
    return [r for r in RUTAS if puede(rol, r, "GET")]


# ---------------------------------------------------------------------
# 4. Rutas que intentan salirse de su recurso
#
# El permiso se decide con el PRIMER tramo de la ruta (/api/cargos/...),
# pero al microservicio se le reenvia la ruta completa. Si en el resto
# viene un "..", la biblioteca que hace el reenvio lo resuelve y la
# peticion termina en OTRO recurso del mismo servicio, con el permiso del
# primero: /api/cargos/../tarifas se revisaba como "cargos" y llegaba a
# "tarifas". Asi la Fundacion podia crear tarifas y el Medico general
# leer los cargos.
#
# Ninguna pantalla del sistema arma rutas con "..", barras invertidas ni
# barras repetidas, asi que rechazarlas no le quita nada a nadie.
# ---------------------------------------------------------------------

# Capas de codificacion que se deshacen como maximo. Un navegador codifica
# una vez; "%252e%252e" (codificado dos veces) ya es alguien intentando
# que la validacion vea una cosa y el servicio otra. Si despues de cinco
# capas el texto todavia cambia, no es una ruta legitima.
MAX_DECODIFICACIONES = 5


def ruta_sospechosa(resto: str) -> bool:
    """
    Responde si el resto de la ruta intenta salirse de su recurso.

    Se decodifica primero, todas las veces que haga falta, para que
    "%2e%2e", "%252e%252e" o "%5c" no se escapen de la revision: lo que
    se valida tiene que ser lo mismo que terminaria interpretando el
    microservicio.

    Se rechaza:
      - cualquier tramo ".."           -> subir de carpeta
      - cualquier barra invertida "\\"  -> algunos servidores la toman por "/"
      - barras repetidas "//"          -> otra forma de alterar la ruta
    """
    texto = resto
    for _ in range(MAX_DECODIFICACIONES):
        decodificado = unquote(texto)
        if decodificado == texto:
            break
        texto = decodificado
    else:
        return True

    if "\\" in texto or "//" in texto:
        return True
    return any(tramo == ".." for tramo in texto.split("/"))
