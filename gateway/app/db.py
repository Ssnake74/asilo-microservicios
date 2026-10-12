"""
Capa de Acceso a Datos del Gateway (esquema asilo_gateway): usuarios,
sesiones, intentos fallidos y bitacora. Es el unico archivo del gateway
con SQL.

Las sesiones van en la base y no en memoria: sobreviven a un reinicio
del gateway y se cierran de verdad borrando la fila.
"""

import os
import time
from datetime import date, datetime

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
    # Con DB_SSL_CA la conexion va cifrada y se verifica el certificado del
    # servidor. En Azure es obligatorio; en desarrollo queda sin definir.
    "ssl_ca": os.getenv("DB_SSL_CA") or None,
}

# Horas sin actividad tras las que vence la sesion (RF-05).
HORAS_DE_SESION = 8

# ---------------------------------------------------------------------
# Bloqueo por intentos fallidos
#
# Cinco fallos dentro de una ventana corrediza de quince minutos. El
# bloqueo se levanta solo cuando el quinto fallo mas reciente sale de
# la ventana.
# ---------------------------------------------------------------------
INTENTOS_PERMITIDOS = 5
MINUTOS_DE_VENTANA = 15

# Los intentos viejos se borran: son un registro de actividad de personas.
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
# Sin llave foranea contra usuarios a proposito: tambien se anotan los
# nombres que no existen, para que el bloqueo no delate cuales son
# validos.
#
# El indice (usuario, fecha) abarata la pregunta de cada ingreso:
# cuantos fallos tiene este usuario en los ultimos quince minutos.
#
# 45 caracteres para el origen: lo que mide una direccion IPv6.
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
# Quien cambio que y cuando. Que se anota lo decide main.py.
#
# Nunca se guarda el cuerpo de la peticion: por ahi viajan contrasenas
# y datos medicos de los internos.
#
# usuario y rol admiten NULL: un rechazo 401 es de alguien sin identificar.
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

# Usuarios de demostracion, todos con la misma contrasena. Los nombres
# llevan tildes porque se ven en pantalla; los nombres de usuario van
# sin tildes y en minusculas porque se escriben a mano.
USUARIOS_SEMILLA = [
    ("admin",      "Julio César Sagastume",  ADMIN),
    ("secretaria", "Marta Lucía González",   SECRETARIA),
    ("medico",     "Dr. Luis Marroquín",     MEDICO_GENERAL),
    ("fundacion",  "Lic. Ana Beatriz Rivas", FUNDACION),
    ("caja",       "Sergio Estuardo López",  CAJA),
]
CONTRASENA_DEMO = "asilo2026"


def init_db(intentos: int = 15, espera: float = 3.0) -> None:
    """
    Crea las tablas y los usuarios de demostracion si no existen.
    Reintenta porque MySQL tarda mas que este contenedor en aceptar conexiones.
    """
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
    """Devuelve la fila completa, contrasena cifrada incluida, o None si no hay usuario activo."""
    conn = get_conn()
    with conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM usuarios WHERE usuario = %s AND activo = TRUE", (usuario,)
            )
            return cur.fetchone()


# =====================================================================
# Sesiones
# =====================================================================

def abrir_sesion(token: str, usuario_id: int) -> None:
    conn = get_conn()
    with conn:
        with conn.cursor() as cur:
            # Aprovecha el login para limpiar sesiones ya vencidas.
            cur.execute("DELETE FROM sesiones WHERE expira < NOW()")
            # Y de paso los intentos fallidos viejos.
            cur.execute(
                "DELETE FROM intentos_fallidos WHERE fecha < NOW() - INTERVAL %s HOUR",
                (HORAS_DE_RETENCION_INTENTOS,),
            )
            cur.execute(
                """INSERT INTO sesiones (token, usuario_id, expira)
                   VALUES (%s, %s, NOW() + INTERVAL %s HOUR)""",
                (token, usuario_id, HORAS_DE_SESION),
            )
        conn.commit()


def usuario_de_sesion(token: str) -> dict | None:
    """
    Devuelve el usuario dueno del token, o None si no existe o vencio.

    El JOIN es valido porque ambas tablas viven en asilo_gateway. Nunca
    se hace un JOIN contra el esquema de otro microservicio.
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
            fila = cur.fetchone()
            if fila is not None:
                # Cada peticion valida renueva el plazo (RF-05).
                cur.execute(
                    "UPDATE sesiones SET expira = NOW() + INTERVAL %s HOUR WHERE token = %s",
                    (HORAS_DE_SESION, token),
                )
        conn.commit()
    return _normalizar(fila)


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
    Anota un ingreso rechazado, tambien cuando el usuario no existe: asi
    "secretaria" y "secretarias" se bloquean igual y el conteo no delata
    cuales nombres son validos.
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

    Se piden los ultimos cinco fallos dentro de la ventana. Si hay cinco,
    manda el mas antiguo: cuando salga de la ventana el ingreso se abre
    solo, sin guardar una fecha de desbloqueo.

    Los minutos se calculan en SQL para que cuente la hora del motor,
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
    Borra los fallos de un usuario al entrar bien: quien acerto tras
    cuatro errores no debe quedar a uno solo de bloquearse.
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
    """Anota una linea. Que se anota lo decide main.py."""
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


# Tope de filas por consulta, para no cargar la bitacora entera de golpe.
LIMITE_BITACORA = 500


def consultar_bitacora(usuario: str | None = None, desde: str | None = None,
                       hasta: str | None = None, limite: int = 200) -> list[dict]:
    """
    Devuelve las lineas de la bitacora, de la mas reciente a la mas vieja.

    Los filtros se pegan al SQL segun vengan, pero los valores van
    siempre como parametros (%s), nunca concatenados: eso evita la
    inyeccion SQL.

    A 'hasta' sin hora se le suma un dia, para que "hasta el 9" incluya
    el 9 completo.
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
