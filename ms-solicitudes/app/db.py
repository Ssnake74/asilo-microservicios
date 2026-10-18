"""
Capa de Acceso a Datos del microservicio de Solicitudes y Visitas Medicas.

Es el unico archivo del servicio con SQL. Trabaja solo en su esquema
(asilo_solicitudes) con su propio usuario: lo que necesita de otro
servicio se lo pide por HTTP (cliente_cobros.py).
"""

import os
import time
from datetime import date, datetime

import pymysql
from pymysql.cursors import DictCursor


# ---------------------------------------------------------------------
# Conexion
#
# Los datos de conexion llegan por variables de entorno desde
# docker-compose.yml. El puerto es el 3306: el 3307 solo existe hacia
# afuera, para conectarse desde el equipo.
# ---------------------------------------------------------------------

CONFIG = {
    "host": os.getenv("DB_HOST", "mysql"),
    "port": int(os.getenv("DB_PORT", "3306")),
    "user": os.getenv("DB_USER", "u_solicitudes"),
    "password": os.getenv("DB_PASSWORD", "solicitudes_2026"),
    "database": os.getenv("DB_NAME", "asilo_solicitudes"),
    "charset": "utf8mb4",
    "cursorclass": DictCursor,
    # Con DB_SSL_CA la conexion va cifrada y se verifica el certificado del
    # servidor. En Azure es obligatorio; en desarrollo queda sin definir.
    "ssl_ca": os.getenv("DB_SSL_CA") or None,
}


def get_conn() -> pymysql.connections.Connection:
    """Abre una conexion nueva a MySQL."""
    return pymysql.connect(**CONFIG)


# ---------------------------------------------------------------------
# Esquema
#
# Los largos de cada VARCHAR salen de los Field(max_length=...) de
# schemas.py, para que Pydantic y MySQL validen lo mismo.
#
# Cada CREATE TABLE va por separado y en orden: primero "solicitudes",
# porque "visitas" la referencia con una llave foranea.
# ---------------------------------------------------------------------

TABLA_SOLICITUDES = """
CREATE TABLE IF NOT EXISTS solicitudes (
    id                    INT AUTO_INCREMENT PRIMARY KEY,
    paciente_id           VARCHAR(40)  NOT NULL,
    paciente_nombre       VARCHAR(120) NOT NULL,
    familiar_email        VARCHAR(120) NULL,
    medico_general        VARCHAR(120) NOT NULL,
    especialidad_remitida VARCHAR(60)  NOT NULL,
    especialidad_id       INT          NULL,
    motivo                VARCHAR(400) NOT NULL,
    cubierto_fundacion    BOOLEAN      NOT NULL DEFAULT TRUE,
    estado                VARCHAR(12)  NOT NULL DEFAULT 'PENDIENTE',
    fecha_solicitud       DATETIME     NOT NULL,
    INDEX idx_estado (estado),
    INDEX idx_paciente (paciente_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""

# solicitud_id es UNIQUE: una solicitud genera una sola visita. main.py
# lo valida, y la base lo garantiza aunque el codigo se equivoque.
TABLA_VISITAS = """
CREATE TABLE IF NOT EXISTS visitas (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    solicitud_id    INT          NOT NULL UNIQUE,
    paciente_id     VARCHAR(40)  NOT NULL,
    paciente_nombre VARCHAR(120) NOT NULL,
    medico_id       INT          NULL,
    medico_tratante VARCHAR(120) NOT NULL,
    especialidad    VARCHAR(60)  NOT NULL,
    enfermero_id    INT          NULL,
    enfermero       VARCHAR(120) NULL,
    fecha_visita    DATETIME     NOT NULL,
    observaciones   VARCHAR(400) NULL,
    cargo_id        INT          NULL,
    cargo_generado  BOOLEAN      NOT NULL DEFAULT FALSE,
    INDEX idx_paciente (paciente_id),
    CONSTRAINT fk_visita_solicitud
        FOREIGN KEY (solicitud_id) REFERENCES solicitudes (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""


# Columnas que llegaron con el catalogo. Los identificadores apuntan a
# asilo_catalogo: relacion logica, sin llave foranea. CREATE TABLE IF NOT
# EXISTS no toca una tabla que ya existe, asi que a las bases anteriores
# se les agregan aqui.
COLUMNAS_DEL_CATALOGO = [
    ("solicitudes", "especialidad_id", "INT NULL AFTER especialidad_remitida"),
    ("visitas", "medico_id", "INT NULL AFTER paciente_nombre"),
    ("visitas", "enfermero_id", "INT NULL AFTER especialidad"),
    ("visitas", "enfermero", "VARCHAR(120) NULL AFTER enfermero_id"),
]


def _agregar_columnas_faltantes(cur) -> None:
    for tabla, columna, definicion in COLUMNAS_DEL_CATALOGO:
        cur.execute(
            """SELECT COUNT(*) AS n FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND COLUMN_NAME = %s""",
            (tabla, columna),
        )
        if cur.fetchone()["n"] == 0:
            cur.execute(f"ALTER TABLE {tabla} ADD COLUMN {columna} {definicion}")


def init_db(intentos: int = 15, espera: float = 3.0) -> None:
    """
    Crea las tablas si no existen, esperando a que MySQL este disponible.

    Reintenta porque Docker levanta este contenedor y el de MySQL casi a
    la vez, y MySQL tarda mas en aceptar conexiones.
    """
    ultimo_error = None
    for intento in range(1, intentos + 1):
        try:
            conn = get_conn()
            with conn:
                with conn.cursor() as cur:
                    cur.execute(TABLA_SOLICITUDES)
                    cur.execute(TABLA_VISITAS)
                    _agregar_columnas_faltantes(cur)
                conn.commit()
            print(f"[ms-solicitudes] Conectado a MySQL en el intento {intento}.")
            return
        except pymysql.err.OperationalError as error:
            ultimo_error = error
            print(f"[ms-solicitudes] MySQL aun no responde ({intento}/{intentos}). Reintentando...")
            time.sleep(espera)
    raise RuntimeError(f"No se pudo conectar a MySQL: {ultimo_error}")


# ---------------------------------------------------------------------
# Normalizacion de filas
#
# MySQL devuelve datetime y BOOLEAN como 0 o 1; schemas.py espera texto
# y booleanos. Se convierte aqui, en la frontera de la capa de datos, y
# no en cada endpoint.
# ---------------------------------------------------------------------

def _normalizar(fila: dict | None, campos_bool: tuple[str, ...]) -> dict | None:
    if fila is None:
        return None
    limpia = dict(fila)
    for campo, valor in limpia.items():
        if isinstance(valor, datetime):
            limpia[campo] = valor.isoformat(sep=" ", timespec="seconds")
        elif isinstance(valor, date):
            limpia[campo] = valor.isoformat()
    for campo in campos_bool:
        if campo in limpia:
            limpia[campo] = bool(limpia[campo])
    return limpia


def _normalizar_solicitud(fila: dict | None) -> dict | None:
    return _normalizar(fila, ("cubierto_fundacion",))


def _normalizar_visita(fila: dict | None) -> dict | None:
    return _normalizar(fila, ("cargo_generado",))


# =====================================================================
# Metodos del repositorio: solicitudes
# =====================================================================

def contar_pendientes() -> int:
    conn = get_conn()
    with conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM solicitudes WHERE estado = 'PENDIENTE'")
            return cur.fetchone()["n"]


def crear_solicitud(datos: dict) -> dict:
    """
    Registra la solicitud que genera el medico general.

    La fecha va sin microsegundos: para una solicitud medica no aportan
    nada.
    """
    conn = get_conn()
    with conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO solicitudes (
                       paciente_id, paciente_nombre, familiar_email, medico_general,
                       especialidad_remitida, especialidad_id, motivo, cubierto_fundacion,
                       estado, fecha_solicitud)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'PENDIENTE', %s)""",
                (
                    datos["paciente_id"],
                    datos["paciente_nombre"],
                    datos["familiar_email"],
                    datos["medico_general"],
                    datos["especialidad_remitida"],
                    datos["especialidad_id"],
                    datos["motivo"],
                    datos["cubierto_fundacion"],
                    datetime.now().replace(microsecond=0),
                ),
            )
            nuevo_id = cur.lastrowid
            cur.execute("SELECT * FROM solicitudes WHERE id = %s", (nuevo_id,))
            fila = cur.fetchone()
        conn.commit()
    return _normalizar_solicitud(fila)


def listar_solicitudes(estado: str | None = None, paciente_id: str | None = None) -> list[dict]:
    """
    Lista las solicitudes, opcionalmente filtradas.

    El SQL se arma por partes, pero los valores siempre viajan como
    parametros (%s), nunca concatenados: eso evita la inyeccion SQL.
    """
    sql = "SELECT * FROM solicitudes WHERE 1 = 1"
    params: list = []
    if estado:
        sql += " AND estado = %s"
        params.append(estado.upper())
    if paciente_id:
        sql += " AND paciente_id = %s"
        params.append(paciente_id)
    sql += " ORDER BY id DESC"

    conn = get_conn()
    with conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            filas = cur.fetchall()
    return [_normalizar_solicitud(f) for f in filas]


def obtener_solicitud(solicitud_id: int) -> dict | None:
    conn = get_conn()
    with conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM solicitudes WHERE id = %s", (solicitud_id,))
            fila = cur.fetchone()
    return _normalizar_solicitud(fila)


def anular_solicitud(solicitud_id: int) -> bool:
    """
    Marca la solicitud como ANULADA. Devuelve False si ya no estaba
    pendiente (por ejemplo, si alguien mas la convirtio mientras tanto).

    El WHERE incluye el estado a proposito: la comprobacion y el cambio
    ocurren en la misma instruccion y no queda hueco entre ambas.
    """
    conn = get_conn()
    with conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE solicitudes SET estado = 'ANULADA' WHERE id = %s AND estado = 'PENDIENTE'",
                (solicitud_id,),
            )
            cambiadas = cur.rowcount
        conn.commit()
    return cambiadas > 0


# =====================================================================
# Metodos del repositorio: visitas
# =====================================================================

def convertir_en_visita(solicitud: dict, datos_visita: dict) -> dict | None:
    """
    Crea la visita medica y deja la solicitud en estado CONVERTIDA.

    Las dos operaciones van en la misma transaccion: no puede quedar una
    visita colgada de una solicitud que sigue pendiente.

    Devuelve None si la solicitud ya no estaba PENDIENTE: si dos usuarios
    la convierten a la vez, solo un UPDATE encuentra fila, y al otro
    main.py le responde 409.
    """
    conn = get_conn()
    with conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE solicitudes SET estado = 'CONVERTIDA'
                   WHERE id = %s AND estado = 'PENDIENTE'""",
                (solicitud["id"],),
            )
            if cur.rowcount == 0:
                conn.rollback()
                return None

            cur.execute(
                """INSERT INTO visitas (
                       solicitud_id, paciente_id, paciente_nombre, medico_id, medico_tratante,
                       especialidad, enfermero_id, enfermero, fecha_visita, observaciones,
                       cargo_generado)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, FALSE)""",
                (
                    solicitud["id"],
                    solicitud["paciente_id"],
                    solicitud["paciente_nombre"],
                    datos_visita["medico_id"],
                    datos_visita["medico_tratante"],
                    datos_visita["especialidad"],
                    datos_visita["enfermero_id"],
                    datos_visita["enfermero"],
                    datos_visita["fecha_visita"],
                    datos_visita["observaciones"],
                ),
            )
            nueva_id = cur.lastrowid
            cur.execute("SELECT * FROM visitas WHERE id = %s", (nueva_id,))
            fila = cur.fetchone()
        conn.commit()
    return _normalizar_visita(fila)


def registrar_cargo_en_visita(visita_id: int, cargo_id: int | None) -> dict | None:
    """
    Anota en la visita el cargo que devolvio el microservicio de Cobros.

    Va aparte, despues de la conversion, porque entre una y otra hay una
    peticion HTTP: una transaccion abierta mientras se espera la red
    bloquearia filas durante segundos.
    """
    conn = get_conn()
    with conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE visitas SET cargo_id = %s, cargo_generado = %s WHERE id = %s",
                (cargo_id, cargo_id is not None, visita_id),
            )
            cur.execute("SELECT * FROM visitas WHERE id = %s", (visita_id,))
            fila = cur.fetchone()
        conn.commit()
    return _normalizar_visita(fila)


def listar_visitas(paciente_id: str | None = None) -> list[dict]:
    sql = "SELECT * FROM visitas WHERE 1 = 1"
    params: list = []
    if paciente_id:
        sql += " AND paciente_id = %s"
        params.append(paciente_id)
    sql += " ORDER BY id DESC"

    conn = get_conn()
    with conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            filas = cur.fetchall()
    return [_normalizar_visita(f) for f in filas]


def obtener_visita(visita_id: int) -> dict | None:
    conn = get_conn()
    with conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM visitas WHERE id = %s", (visita_id,))
            fila = cur.fetchone()
    return _normalizar_visita(fila)


def visitas_sin_cargo() -> list[dict]:
    """
    Visitas cuyo cargo no se pudo generar, con lo que hace falta para
    pedirlo otra vez (RNF-13). El JOIN es valido: las dos tablas viven en
    asilo_solicitudes.
    """
    conn = get_conn()
    with conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT v.id, s.paciente_id, s.paciente_nombre, s.familiar_email,
                          s.cubierto_fundacion
                   FROM visitas v JOIN solicitudes s ON s.id = v.solicitud_id
                   WHERE v.cargo_generado = FALSE AND v.cargo_id IS NULL"""
            )
            return [_normalizar(f, ("cubierto_fundacion",)) for f in cur.fetchall()]
