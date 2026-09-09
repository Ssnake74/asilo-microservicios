"""
Capa de Acceso a Datos del Gateway.

Guarda cuatro cosas en el esquema asilo_gateway:

  usuarios           quien puede entrar y con que rol
  sesiones           que tokens estan activos en este momento
  intentos_fallidos  ingresos rechazados, para poder bloquear
  bitacora           quien cambio que cosa y cuando

Guardar las sesiones en la base y no solo en memoria tiene una ventaja
concreta: si el gateway se reinicia, nadie pierde la sesion. Y permite
cerrar sesion de verdad, borrando la fila, cosa que un token firmado
tipo JWT no permite sin trabajo extra.

Como en el resto del proyecto, este es el UNICO archivo del gateway con
SQL. main.py no escribe consultas: llama funciones con nombre.
"""

import os
import time
from datetime import date, datetime, timedelta

import pymysql
from pymysql.cursors import DictCursor

from .seguridad import ADMIN, CAJA, FUNDACION, MEDICO_GENERAL, SECRETARIA, cifrar_contrasena

CONFIG = {
    "host": os.getenv("DB_HOST", "mysql"),
    "port": int(os.getenv("DB_PORT", "3306")),
    "user": os.getenv("DB_USER", "u_gateway"),
    "password": os.getenv("DB_PASSWORD", "gateway_2026"),
    "database": os.getenv("DB_NAME", "asilo_gateway"),
    "charset": "utf8mb4",
    "cursorclass": DictCursor,
}

# Cuanto dura una sesion sin actividad.
HORAS_DE_SESION = 8

# ---------------------------------------------------------------------
# Reglas del bloqueo por intentos fallidos
#
# Cinco intentos fallidos dentro de una ventana de quince minutos dejan
# al usuario bloqueado otros quince. Los numeros estan aqui arriba, con
# nombre, para poder cambiarlos sin buscarlos dentro de una consulta.
#
# La ventana es CORREDIZA: se cuentan los fallos de los ultimos quince
# minutos. El bloqueo se levanta solo cuando el quinto fallo mas
# reciente cumple quince minutos y sale de la ventana.
# ---------------------------------------------------------------------
INTENTOS_PERMITIDOS = 5
MINUTOS_DE_VENTANA = 15

# Los intentos viejos no sirven para nada y no deben quedarse guardados
# mas de la cuenta: son un registro de actividad de personas.
HORAS_DE_RETENCION_INTENTOS = 24


def get_conn() -> pymysql.connections.Connection:
    return pymysql.connect(**CONFIG)


TABLA_USUARIOS = """
CREATE TABLE IF NOT EXISTS usuarios (
    id           INT AUTO_INCREMENT PRIMARY KEY,
    usuario      VARCHAR(40)  NOT NULL UNIQUE,
    nombre       VARCHAR(120) NOT NULL,
    contrasena   VARCHAR(200) NOT NULL,
    rol          VARCHAR(20)  NOT NULL,
    activo       BOOLEAN      NOT NULL DEFAULT TRUE,
    fecha_alta   DATETIME     NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""

# ON DELETE CASCADE: si se borra un usuario, sus sesiones se van con el.
TABLA_SESIONES = """
CREATE TABLE IF NOT EXISTS sesiones (
    token       VARCHAR(64)  NOT NULL PRIMARY KEY,
    usuario_id  INT          NOT NULL,
    expira      DATETIME     NOT NULL,
    INDEX idx_expira (expira),
    CONSTRAINT fk_sesion_usuario FOREIGN KEY (usuario_id)
        REFERENCES usuarios (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""

# ---------------------------------------------------------------------
# Intentos de ingreso fallidos
#
# No lleva llave foranea contra usuarios A PROPOSITO. Tambien hay que
# anotar los intentos contra nombres que NO existen: si solo se contaran
# los usuarios reales, probar "admin" quedaria registrado y probar
# "adminn" no, y esa diferencia -por ejemplo, que uno se bloquee y el
# otro nunca- le revelaria a un atacante cuales nombres son validos.
#
# El indice por (usuario, fecha) es el que hace barata la pregunta que
# se hace en cada ingreso: cuantos fallos tiene este usuario en los
# ultimos quince minutos.
#
# 45 caracteres para el origen: es lo que mide una direccion IPv6.
# ---------------------------------------------------------------------
TABLA_INTENTOS_FALLIDOS = """
CREATE TABLE IF NOT EXISTS intentos_fallidos (
    id       INT AUTO_INCREMENT PRIMARY KEY,
    usuario  VARCHAR(40) NOT NULL,
    origen   VARCHAR(45) NOT NULL,
    fecha    DATETIME    NOT NULL,
    INDEX idx_usuario_fecha (usuario, fecha)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""

# ---------------------------------------------------------------------
# Bitacora de auditoria
#
# Responde a "quien cambio esto y cuando". Solo se anotan las
# operaciones que MODIFICAN datos y los intentos rechazados; las
# consultas no, porque llenarian la tabla sin aportar nada.
#
# NUNCA se guarda el cuerpo de la peticion. Por ahi viajan contrasenas
# y datos medicos de los internos, y una bitacora que los copie se
# convierte ella misma en el problema que venia a resolver.
#
# usuario y rol admiten NULL: un intento rechazado con 401 es
# justamente alguien de quien todavia no se sabe quien es.
# ---------------------------------------------------------------------
TABLA_BITACORA = """
CREATE TABLE IF NOT EXISTS bitacora (
    id      INT AUTO_INCREMENT PRIMARY KEY,
    fecha   DATETIME     NOT NULL,
    usuario VARCHAR(40)  NULL,
    rol     VARCHAR(20)  NULL,
    metodo  VARCHAR(10)  NOT NULL,
    recurso VARCHAR(200) NOT NULL,
    codigo  INT          NOT NULL,
    origen  VARCHAR(45)  NOT NULL,
    INDEX idx_fecha (fecha),
    INDEX idx_usuario (usuario)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""

# Usuarios de demostracion. La contrasena es la misma para todos a
# proposito, para que la demostracion sea fluida. En un sistema real
# cada quien pone la suya y se obliga a cambiarla al primer ingreso.
USUARIOS_SEMILLA = [
    ("admin",      "Julio Cesar Sagastume",  ADMIN),
    ("secretaria", "Marta Lucia Gonzalez",   SECRETARIA),
    ("medico",     "Dr. Luis Marroquin",     MEDICO_GENERAL),
    ("fundacion",  "Lic. Ana Beatriz Rivas", FUNDACION),
    ("caja",       "Sergio Estuardo Lopez",  CAJA),
]
CONTRASENA_DEMO = "asilo2026"


def init_db(intentos: int = 15, espera: float = 3.0) -> None:
    ultimo_error = None
    for intento in range(1, intentos + 1):
        try:
            conn = get_conn()
            with conn:
                with conn.cursor() as cur:
                    # En orden de dependencia: sesiones apunta a usuarios.
                    cur.execute(TABLA_USUARIOS)
                    cur.execute(TABLA_SESIONES)
                    cur.execute(TABLA_INTENTOS_FALLIDOS)
                    cur.execute(TABLA_BITACORA)
                    cur.execute("SELECT COUNT(*) AS n FROM usuarios")
                    if cur.fetchone()["n"] == 0:
                        ahora = datetime.now().replace(microsecond=0)
                        cur.executemany(
                            """INSERT INTO usuarios (usuario, nombre, contrasena, rol, fecha_alta)
                               VALUES (%s, %s, %s, %s, %s)""",
                            [
                                (u, n, cifrar_contrasena(CONTRASENA_DEMO), r, ahora)
                                for u, n, r in USUARIOS_SEMILLA
                            ],
                        )
                        print("[gateway] Usuarios de demostracion creados.", flush=True)
                conn.commit()
            print(f"[gateway] Conectado a MySQL en el intento {intento}.", flush=True)
            return
        except pymysql.err.OperationalError as error:
            ultimo_error = error
            print(f"[gateway] MySQL aun no responde ({intento}/{intentos}).", flush=True)
            time.sleep(espera)
    raise RuntimeError(f"No se pudo conectar a MySQL: {ultimo_error}")


def _normalizar(fila: dict | None) -> dict | None:
    if fila is None:
        return None
    limpia = dict(fila)
    for campo, valor in limpia.items():
        if isinstance(valor, datetime):
            limpia[campo] = valor.isoformat(sep=" ", timespec="seconds")
        elif isinstance(valor, date):
            limpia[campo] = valor.isoformat()
    if "activo" in limpia:
        limpia["activo"] = bool(limpia["activo"])
    limpia.pop("contrasena", None)  # nunca sale de esta capa
    return limpia


# =====================================================================
# Usuarios
# =====================================================================

def buscar_usuario(usuario: str) -> dict | None:
    """Devuelve la fila COMPLETA, con la contrasena cifrada incluida."""
    conn = get_conn()
    with conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM usuarios WHERE usuario = %s AND activo = TRUE", (usuario,)
            )
            return cur.fetchone()


def listar_usuarios() -> list[dict]:
    conn = get_conn()
    with conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM usuarios ORDER BY rol, usuario")
            return [_normalizar(f) for f in cur.fetchall()]


# =====================================================================
# Sesiones
# =====================================================================

def abrir_sesion(token: str, usuario_id: int) -> None:
    conn = get_conn()
    with conn:
        with conn.cursor() as cur:
            # Aprovecha el login para limpiar sesiones ya vencidas.
            cur.execute("DELETE FROM sesiones WHERE expira < NOW()")
            # Y de paso los intentos fallidos viejos, por la misma razon:
            # es el momento en que ya se esta escribiendo en la base.
            cur.execute(
                "DELETE FROM intentos_fallidos WHERE fecha < NOW() - INTERVAL %s HOUR",
                (HORAS_DE_RETENCION_INTENTOS,),
            )
            cur.execute(
                "INSERT INTO sesiones (token, usuario_id, expira) VALUES (%s, %s, %s)",
                (token, usuario_id, datetime.now() + timedelta(hours=HORAS_DE_SESION)),
            )
        conn.commit()


def usuario_de_sesion(token: str) -> dict | None:
    """
    Devuelve el usuario dueno del token, o None si no existe o vencio.

    El JOIN entre sesiones y usuarios es valido porque ambas tablas
    viven en el MISMO esquema (asilo_gateway). Nunca se hace un JOIN
    contra los esquemas de otros microservicios.
    """
    conn = get_conn()
    with conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT u.id, u.usuario, u.nombre, u.rol, u.activo, s.expira
                   FROM sesiones s
                   JOIN usuarios u ON u.id = s.usuario_id
                   WHERE s.token = %s AND s.expira > NOW() AND u.activo = TRUE""",
                (token,),
            )
            return _normalizar(cur.fetchone())


def cerrar_sesion(token: str) -> None:
    conn = get_conn()
    with conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM sesiones WHERE token = %s", (token,))
        conn.commit()


# =====================================================================
# Intentos fallidos de ingreso
# =====================================================================

def registrar_intento_fallido(usuario: str, origen: str) -> None:
    """
    Anota un ingreso rechazado.

    Se llama TAMBIEN cuando el usuario no existe. Es lo que hace que el
    conteo no delate cuales nombres son validos: probar "secretaria" y
    probar "secretarias" se bloquean igual.
    """
    conn = get_conn()
    with conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO intentos_fallidos (usuario, origen, fecha) VALUES (%s, %s, %s)",
                (usuario, origen, datetime.now().replace(microsecond=0)),
            )
        conn.commit()


def minutos_de_bloqueo(usuario: str) -> int:
    """
    Minutos que le faltan a este usuario para poder volver a intentar.
    Devuelve 0 si no esta bloqueado.

    Como funciona: se piden los ultimos cinco fallos que caen dentro de
    la ventana de quince minutos. Si no hay cinco, no hay bloqueo. Si si
    los hay, el mas ANTIGUO de esos cinco es el que manda: cuando el
    cumpla quince minutos saldra de la ventana, quedaran cuatro y el
    ingreso se abrira solo. No hace falta guardar una fecha de
    desbloqueo ni un proceso que la revise.

    El calculo de los minutos se hace en SQL (TIMESTAMPDIFF) y no en
    Python a proposito: asi la hora que cuenta es siempre la del motor,
    aunque el contenedor del gateway tuviera otra.
    """
    conn = get_conn()
    with conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT TIMESTAMPDIFF(SECOND, NOW(), fecha + INTERVAL %s MINUTE) AS faltan
                   FROM intentos_fallidos
                   WHERE usuario = %s AND fecha > NOW() - INTERVAL %s MINUTE
                   ORDER BY fecha DESC
                   LIMIT %s""",
                (MINUTOS_DE_VENTANA, usuario, MINUTOS_DE_VENTANA, INTENTOS_PERMITIDOS),
            )
            filas = cur.fetchall()

    if len(filas) < INTENTOS_PERMITIDOS:
        return 0

    # El ultimo de la lista es el mas antiguo de los cinco.
    segundos = filas[-1]["faltan"] or 0
    if segundos <= 0:
        return 0
    # Se redondea hacia arriba: faltando 10 segundos se dice "1 minuto",
    # no "0 minutos", que sonaria a que ya puede entrar.
    return (segundos + 59) // 60


def limpiar_intentos(usuario: str) -> None:
    """
    Borra los fallos de un usuario. Se llama al entrar bien.

    Sin esto, alguien que se equivoco cuatro veces y a la quinta
    acerto quedaria a un solo error de bloquearse durante los proximos
    quince minutos, ya habiendo demostrado que es quien dice ser.
    """
    conn = get_conn()
    with conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM intentos_fallidos WHERE usuario = %s", (usuario,))
        conn.commit()


# =====================================================================
# Bitacora de auditoria
# =====================================================================

def registrar_en_bitacora(usuario: str | None, rol: str | None, metodo: str,
                          recurso: str, codigo: int, origen: str) -> None:
    """Anota una linea. Quien decide QUE se anota es main.py."""
    conn = get_conn()
    with conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO bitacora (fecha, usuario, rol, metodo, recurso, codigo, origen)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                (
                    datetime.now().replace(microsecond=0),
                    usuario, rol, metodo, recurso[:200], codigo, origen,
                ),
            )
        conn.commit()


# Tope de filas que puede devolver una consulta a la bitacora. Existe
# para que pedirla entera no termine cargando cien mil filas de golpe.
LIMITE_BITACORA = 500


def consultar_bitacora(usuario: str | None = None, desde: str | None = None,
                       hasta: str | None = None, limite: int = 200) -> list[dict]:
    """
    Devuelve las lineas de la bitacora, de la mas reciente a la mas vieja.

    Los filtros se van pegando al SQL segun vengan, pero los valores
    viajan SIEMPRE como parametros (%s), nunca concatenados: eso es lo
    que evita la inyeccion SQL. Es el mismo patron de listar() en los
    demas microservicios.

    En 'hasta' se suma un dia cuando viene solo la fecha: quien escribe
    "hasta el 9 de septiembre" espera que se incluya ese dia completo, y
    un DATETIME del 9 a las 15:00 es mayor que "2026-09-09 00:00:00".
    """
    sql = "SELECT * FROM bitacora WHERE 1 = 1"
    params: list = []

    if usuario:
        sql += " AND usuario = %s"
        params.append(usuario.strip().lower())
    if desde:
        sql += " AND fecha >= %s"
        params.append(desde)
    if hasta:
        if len(hasta.strip()) == 10:  # viene "AAAA-MM-DD", sin hora
            sql += " AND fecha < %s + INTERVAL 1 DAY"
        else:
            sql += " AND fecha <= %s"
        params.append(hasta)

    sql += " ORDER BY fecha DESC, id DESC LIMIT %s"
    params.append(max(1, min(int(limite), LIMITE_BITACORA)))

    conn = get_conn()
    with conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return [_normalizar(f) for f in cur.fetchall()]
