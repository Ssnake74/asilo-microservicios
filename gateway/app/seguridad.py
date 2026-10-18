"""
Seguridad y enrutamiento del Gateway.

Cuatro cosas que no dependen de HTTP ni de la base, y se prueban solas:

  1. Como se guardan y verifican las contrasenas.
  2. La tabla de rutas: que microservicio atiende cada recurso.
  3. La tabla de permisos: que rol puede hacer que cosa.
  4. La deteccion de rutas que intentan salirse de su recurso.
"""

import hashlib
import hmac
import os
import secrets
from urllib.parse import unquote

# ---------------------------------------------------------------------
# 1. Contrasenas
#
# Se guarda el resultado de PBKDF2, no la contrasena, con una sal al
# azar por usuario. Las 200,000 repeticiones hacen lento probar
# contrasenas a la fuerza.
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
    Compara la contrasena escrita contra lo guardado. Devuelve False si lo
    guardado no tiene la forma 'sal$resumen'.

    compare_digest y no ==: el == corta en la primera diferencia, y el
    tiempo de respuesta dejaria adivinar caracter por caracter.
    """
    try:
        sal, _ = guardado.split("$", 1)
    except ValueError:
        return False
    return hmac.compare_digest(cifrar_contrasena(contrasena, sal), guardado)


def nuevo_token() -> str:
    """Token de sesion al azar, de 32 bytes."""
    return secrets.token_urlsafe(32)


# Sin 0/o, 1/l ni i: la contrasena temporal se dicta o se copia de un
# papel, y esas letras se confunden.
LETRAS_TEMPORAL = "abcdefghjkmnpqrstuvwxyz23456789"


def contrasena_temporal() -> str:
    """Contrasena al azar para un usuario nuevo o que olvido la suya, como 'k7mq-4tzp-x2ra'."""
    return "-".join(
        "".join(secrets.choice(LETRAS_TEMPORAL) for _ in range(4)) for _ in range(3)
    )


MINIMO_CONTRASENA = 8


def problema_de_contrasena(nueva: str, usuario: str) -> str | None:
    """
    Dice que le falta a una contrasena elegida por la persona, o None si
    sirve. Ocho caracteres con letras y numeros: suficiente con el bloqueo
    por intentos, y facil de recordar para personal que no es tecnico.
    """
    if len(nueva) < MINIMO_CONTRASENA:
        return f"La contraseña nueva debe tener al menos {MINIMO_CONTRASENA} caracteres."
    if not any(c.isalpha() for c in nueva) or not any(c.isdigit() for c in nueva):
        return "La contraseña nueva debe combinar letras y números."
    if nueva.strip().lower() == usuario.lower():
        return "La contraseña nueva no puede ser igual al nombre de usuario."
    return None


# ---------------------------------------------------------------------
# 2. Tabla de rutas
#
# /api/pacientes se reenvia a http://ms-pacientes:8083/pacientes.
#
# Se enruta por recurso y no por servicio: el frontend no necesita saber
# que "visitas" y "solicitudes" viven en el mismo contenedor.
# ---------------------------------------------------------------------

MS_PACIENTES = os.getenv("MS_PACIENTES_URL", "http://ms-pacientes:8083")
MS_SOLICITUDES = os.getenv("MS_SOLICITUDES_URL", "http://ms-solicitudes:8081")
MS_COBROS = os.getenv("MS_COBROS_URL", "http://ms-cobros:8082")
MS_CATALOGO = os.getenv("MS_CATALOGO_URL", "http://ms-catalogo:8084")
MS_CLINICO = os.getenv("MS_CLINICO_URL", "http://ms-clinico:8085")

RUTAS: dict[str, tuple[str, str]] = {
    "pacientes":     (MS_PACIENTES,   "/pacientes"),
    "solicitudes":   (MS_SOLICITUDES, "/solicitudes"),
    "visitas":       (MS_SOLICITUDES, "/visitas"),
    "tarifas":       (MS_COBROS,      "/tarifas"),
    "cargos":        (MS_COBROS,      "/cargos"),
    "estado-cuenta": (MS_COBROS,      "/estado-cuenta"),
    # Entradas y salidas del asilo: tambien las lleva cobros.
    "cuotas":        (MS_COBROS,      "/cuotas"),
    "donaciones":    (MS_COBROS,      "/donaciones"),
    "gastos":        (MS_COBROS,      "/gastos"),
    "fundacion":     (MS_COBROS,      "/fundacion"),
    # El catalogo tiene cinco listas; todas viajan bajo /catalogo.
    "catalogo":      (MS_CATALOGO,    "/catalogo"),
    # Atencion medica. Ordenar un examen y registrar su resultado son
    # recursos distintos porque los hacen roles distintos: el permiso se
    # decide por recurso y metodo, y con un solo recurso el laboratorio
    # podria ordenar examenes. Igual con recetas y despachos.
    "fichas":        (MS_CLINICO,     "/fichas"),
    "examenes":      (MS_CLINICO,     "/examenes"),
    "resultados":    (MS_CLINICO,     "/resultados"),
    "recetas":       (MS_CLINICO,     "/recetas"),
    "despachos":     (MS_CLINICO,     "/despachos"),
}

# Para el tablero de estado: nombre visible -> URL de su /health
SERVICIOS = {
    "ms-pacientes":   MS_PACIENTES,
    "ms-solicitudes": MS_SOLICITUDES,
    "ms-cobros":      MS_COBROS,
    "ms-catalogo":    MS_CATALOGO,
    "ms-clinico":     MS_CLINICO,
}


# ---------------------------------------------------------------------
# 3. Roles y permisos
#
#   ADMIN          administrador del sistema, ve y hace todo
#   SECRETARIA     registra a los internos y sus familiares responsables
#   MEDICO_GENERAL evalua al interno y lo remite a una especialidad
#   FUNDACION      asigna horario y medico, y convierte la solicitud en visita
#   CAJA           tarifario, cobros y estado de cuenta de los familiares
#   ESPECIALISTA   atiende la visita y completa la ficha medica
#   LABORATORIO    registra los resultados de los examenes
#   FARMACIA       despacha los medicamentos recetados
#
# Si el rol no aparece en la lista del recurso y el metodo, el gateway
# responde 403 y la peticion no llega al microservicio. Los servicios no
# conocen los roles: eso vive solo aqui.
# ---------------------------------------------------------------------

ADMIN = "ADMIN"
SECRETARIA = "SECRETARIA"
MEDICO_GENERAL = "MEDICO_GENERAL"
FUNDACION = "FUNDACION"
CAJA = "CAJA"
ESPECIALISTA = "ESPECIALISTA"
LABORATORIO = "LABORATORIO"
FARMACIA = "FARMACIA"

ROLES = (ADMIN, SECRETARIA, MEDICO_GENERAL, FUNDACION, CAJA, ESPECIALISTA, LABORATORIO, FARMACIA)

# Nombre de cada rol en pantalla. Lleva tildes porque lo lee la persona,
# en la barra de arriba y cuando se le niega un permiso.
NOMBRE_ROL = {
    ADMIN: "Administrador",
    SECRETARIA: "Secretaria del asilo",
    MEDICO_GENERAL: "Médico general",
    FUNDACION: "Fundación",
    CAJA: "Caja y cobros",
    ESPECIALISTA: "Médico especialista",
    LABORATORIO: "Laboratorio clínico",
    FARMACIA: "Farmacia",
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
        # El especialista ve las visitas para saber a quien atiende.
        "GET":    {ADMIN, SECRETARIA, MEDICO_GENERAL, FUNDACION, ESPECIALISTA},
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
    # La secretaria consulta las cuotas porque atiende al familiar; las
    # registra y las cobra caja.
    "cuotas": {
        "GET":    {ADMIN, SECRETARIA, CAJA},
        "POST":   {ADMIN, CAJA},
        "DELETE": {ADMIN, CAJA},
    },
    "donaciones": {
        "GET":    {ADMIN, CAJA},
        "POST":   {ADMIN, CAJA},
    },
    "gastos": {
        "GET":    {ADMIN, CAJA},
        "POST":   {ADMIN, CAJA},
    },
    # La fundacion ve cuanto se le debe y lo que se le ha pagado; el pago
    # lo registra caja.
    "fundacion": {
        "GET":    {ADMIN, CAJA, FUNDACION},
        "POST":   {ADMIN, CAJA},
    },
    "catalogo": {
        # Todos lo leen para llenar sus listas; lo mantiene la fundacion,
        # que es quien tiene el cuadro de medicos.
        "GET":    TODOS,
        "POST":   {ADMIN, FUNDACION},
        "PUT":    {ADMIN, FUNDACION},
    },
    # El historial medico lo leen los medicos; la secretaria y caja no.
    "fichas": {
        "GET":    {ADMIN, MEDICO_GENERAL, ESPECIALISTA},
        "POST":   {ADMIN, ESPECIALISTA},
    },
    "examenes": {
        "GET":    {ADMIN, MEDICO_GENERAL, ESPECIALISTA, LABORATORIO},
        "POST":   {ADMIN, ESPECIALISTA},
    },
    "resultados": {
        "POST":   {ADMIN, LABORATORIO},
    },
    "recetas": {
        "GET":    {ADMIN, MEDICO_GENERAL, ESPECIALISTA, FARMACIA},
        "POST":   {ADMIN, ESPECIALISTA},
    },
    "despachos": {
        "POST":   {ADMIN, FARMACIA},
    },
}


def puede(rol: str, recurso: str, metodo: str) -> bool:
    """
    Responde si ese rol tiene permiso para ese metodo sobre ese recurso.

    Lo que no esta declarado en PERMISOS se niega: un endpoint nuevo no
    queda abierto por descuido.
    """
    if recurso not in PERMISOS:
        return False
    return rol in PERMISOS[recurso].get(metodo.upper(), set())


def recursos_visibles(rol: str) -> list[str]:
    """Recursos que ese rol puede al menos consultar. Sirve para el menu."""
    return [r for r in RUTAS if puede(rol, r, "GET")]


def recursos_gestionables(rol: str) -> list[str]:
    """Recursos que ese rol puede modificar. El menu los usa para las pantallas de mantenimiento."""
    return [r for r in RUTAS if any(puede(rol, r, m) for m in ("POST", "PUT", "DELETE"))]


# ---------------------------------------------------------------------
# 4. Rutas que intentan salirse de su recurso
#
# El permiso se decide con el primer tramo de la ruta, pero se reenvia la
# ruta completa. Un ".." en el resto lo resuelve la biblioteca del
# reenvio: /api/cargos/../tarifas se revisaria como "cargos" y llegaria
# a "tarifas", con el permiso de cargos.
#
# Ninguna pantalla arma rutas con "..", barras invertidas ni barras
# repetidas, asi que rechazarlas no le quita nada a nadie.
# ---------------------------------------------------------------------

# Capas de codificacion que se deshacen como maximo. Un navegador codifica
# una vez; si despues de cinco capas el texto todavia cambia, no es una
# ruta legitima.
MAX_DECODIFICACIONES = 5


def ruta_sospechosa(resto: str) -> bool:
    """
    Responde si el resto de la ruta intenta salirse de su recurso.

    Se decodifica todas las veces que haga falta, para que "%2e%2e",
    "%252e%252e" o "%5c" no escapen: se valida lo mismo que terminaria
    interpretando el microservicio.

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
