"""
Capa de Acceso a Datos del microservicio de Pacientes.

Es el unico archivo del servicio con SQL y el unico que sabe que el
motor es MySQL. main.py llama a funciones con nombre (crear,
obtener_por_codigo, actualizar...).
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
# docker-compose.yml.
# ---------------------------------------------------------------------

CONFIG = {
    "host": os.getenv("DB_HOST", "mysql"),
    "port": int(os.getenv("DB_PORT", "3306")),
    "user": os.getenv("DB_USER", "u_pacientes"),
    "password": os.getenv("DB_PASSWORD", "pacientes_2026"),
    "database": os.getenv("DB_NAME", "asilo_pacientes"),
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
# Cada VARCHAR declara su largo: MySQL rechaza lo que no quepa en vez de
# guardarlo cortado.
# ---------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS pacientes (
    id                  INT AUTO_INCREMENT PRIMARY KEY,
    codigo              VARCHAR(10)  NULL UNIQUE,
    nombres             VARCHAR(80)  NOT NULL,
    apellidos           VARCHAR(80)  NOT NULL,
    dpi                 VARCHAR(20)  NULL UNIQUE,
    fecha_nacimiento    DATE         NOT NULL,
    sexo                CHAR(1)      NOT NULL,
    tipo_sangre         VARCHAR(5)   NULL,
    fecha_ingreso       DATE         NOT NULL,
    habitacion          VARCHAR(20)  NULL,
    procedencia         VARCHAR(150) NULL,
    familiar_nombre     VARCHAR(120) NOT NULL,
    familiar_parentesco VARCHAR(40)  NULL,
    familiar_telefono   VARCHAR(20)  NOT NULL,
    familiar_email      VARCHAR(120) NULL,
    padecimientos       VARCHAR(400) NULL,
    alergias            VARCHAR(200) NULL,
    cubierto_fundacion  BOOLEAN      NOT NULL DEFAULT TRUE,
    estado              VARCHAR(12)  NOT NULL DEFAULT 'ACTIVO',
    fecha_egreso        DATE         NULL,
    motivo_egreso       VARCHAR(300) NULL,
    fecha_registro      DATETIME     NOT NULL,
    INDEX idx_estado (estado),
    INDEX idx_apellidos (apellidos)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""

# Columnas que el UPDATE tiene permitido tocar. Es una lista blanca:
# evita que un nombre de campo inesperado termine dentro del SQL.
CAMPOS_ACTUALIZABLES = {
    "habitacion", "familiar_nombre", "familiar_parentesco", "familiar_telefono",
    "familiar_email", "padecimientos", "alergias", "cubierto_fundacion", "estado",
    "fecha_egreso", "motivo_egreso",
}

# Columnas del egreso (RF-13). CREATE TABLE IF NOT EXISTS no toca una
# tabla que ya existe, asi que a las bases anteriores se les agregan aqui.
COLUMNAS_DEL_EGRESO = [
    ("fecha_egreso", "ALTER TABLE pacientes ADD COLUMN fecha_egreso DATE NULL AFTER estado"),
    ("motivo_egreso", "ALTER TABLE pacientes ADD COLUMN motivo_egreso VARCHAR(300) NULL AFTER fecha_egreso"),
]


def init_db(intentos: int = 15, espera: float = 3.0) -> None:
    """
    Crea la tabla si no existe, esperando a que MySQL este disponible.

    Reintenta porque Docker levanta este contenedor y el de MySQL casi a
    la vez, y MySQL tarda mas en aceptar conexiones.
    """
    ultimo_error = None
    for intento in range(1, intentos + 1):
        try:
            conn = get_conn()
            with conn:
                with conn.cursor() as cur:
                    cur.execute(SCHEMA)
                    for columna, alter in COLUMNAS_DEL_EGRESO:
                        cur.execute(
                            """SELECT COUNT(*) AS n FROM information_schema.COLUMNS
                               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'pacientes'
                                 AND COLUMN_NAME = %s""",
                            (columna,),
                        )
                        if cur.fetchone()["n"] == 0:
                            cur.execute(alter)
                            print(f"[ms-pacientes] Columna {columna} agregada.", flush=True)
                conn.commit()
            print(f"[ms-pacientes] Conectado a MySQL en el intento {intento}.")
            return
        except pymysql.err.OperationalError as error:
            ultimo_error = error
            print(f"[ms-pacientes] MySQL aun no responde ({intento}/{intentos}). Reintentando...")
            time.sleep(espera)
    raise RuntimeError(f"No se pudo conectar a MySQL: {ultimo_error}")


# ---------------------------------------------------------------------
# Normalizacion de filas
#
# MySQL devuelve date, datetime y BOOLEAN como 0 o 1; schemas.py espera
# texto y booleanos. Se convierte aqui, en la frontera de la capa de
# datos, y no en cada endpoint.
# ---------------------------------------------------------------------

def _normalizar(fila: dict | None) -> dict | None:
    if fila is None:
        return None
    limpia = dict(fila)
    for campo, valor in limpia.items():
        if isinstance(valor, datetime):
            limpia[campo] = valor.isoformat(sep=" ", timespec="seconds")
        elif isinstance(valor, date):
            limpia[campo] = valor.isoformat()
    limpia["cubierto_fundacion"] = bool(limpia.get("cubierto_fundacion"))
    return limpia


# =====================================================================
# Metodos del repositorio
# =====================================================================

def contar_activos() -> int:
    conn = get_conn()
    with conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM pacientes WHERE estado = 'ACTIVO'")
            return cur.fetchone()["n"]


def dpi_ya_registrado(dpi: str) -> str | None:
    """Devuelve el codigo del anciano que ya tiene ese DPI, o None."""
    conn = get_conn()
    with conn:
        with conn.cursor() as cur:
            cur.execute("SELECT codigo FROM pacientes WHERE dpi = %s", (dpi,))
            fila = cur.fetchone()
    return fila["codigo"] if fila else None


def crear(datos: dict) -> dict:
    """
    Da de alta a un anciano y le asigna su codigo correlativo.

    El codigo (PAC-001, PAC-002...) se arma despues del INSERT con el id
    que genera MySQL: dos altas simultaneas nunca calculan el mismo.

    El INSERT y el UPDATE del codigo van en la misma transaccion: si algo
    falla a medias, no queda un registro sin codigo.
    """
    conn = get_conn()
    with conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO pacientes (
                       nombres, apellidos, dpi, fecha_nacimiento, sexo, tipo_sangre,
                       fecha_ingreso, habitacion, procedencia, familiar_nombre,
                       familiar_parentesco, familiar_telefono, familiar_email,
                       padecimientos, alergias, cubierto_fundacion, estado, fecha_registro)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                           'ACTIVO', %s)""",
                (
                    datos["nombres"], datos["apellidos"], datos["dpi"],
                    datos["fecha_nacimiento"], datos["sexo"], datos["tipo_sangre"],
                    datos["fecha_ingreso"], datos["habitacion"], datos["procedencia"],
                    datos["familiar_nombre"], datos["familiar_parentesco"],
                    datos["familiar_telefono"], datos["familiar_email"],
                    datos["padecimientos"], datos["alergias"],
                    datos["cubierto_fundacion"],
                    datetime.now().replace(microsecond=0),
                ),
            )
            nuevo_id = cur.lastrowid
            cur.execute(
                "UPDATE pacientes SET codigo = CONCAT('PAC-', LPAD(%s, 3, '0')) WHERE id = %s",
                (nuevo_id, nuevo_id),
            )
            cur.execute("SELECT * FROM pacientes WHERE id = %s", (nuevo_id,))
            fila = cur.fetchone()
        conn.commit()
    return _normalizar(fila)


def listar(estado: str | None = None, buscar: str | None = None) -> list[dict]:
    sql = "SELECT * FROM pacientes WHERE 1 = 1"
    params: list = []
    if estado:
        sql += " AND estado = %s"
        params.append(estado.upper())
    if buscar:
        sql += " AND (nombres LIKE %s OR apellidos LIKE %s OR codigo LIKE %s)"
        patron = f"%{buscar}%"
        params.extend([patron, patron, patron])
    sql += " ORDER BY id DESC"

    conn = get_conn()
    with conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            filas = cur.fetchall()
    return [_normalizar(f) for f in filas]


def obtener_por_codigo(codigo: str) -> dict | None:
    conn = get_conn()
    with conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM pacientes WHERE codigo = %s", (codigo,))
            fila = cur.fetchone()
    return _normalizar(fila)


def actualizar(codigo: str, cambios: dict) -> dict | None:
    """
    Actualiza solo los campos permitidos. Devuelve None si no existe.

    Los nombres de columna se validan contra CAMPOS_ACTUALIZABLES antes
    de armar el SQL. Los valores siempre viajan como parametros (%s),
    nunca concatenados: eso evita la inyeccion SQL.
    """
    permitidos = {k: v for k, v in cambios.items() if k in CAMPOS_ACTUALIZABLES}
    if not permitidos:
        return None

    asignaciones = ", ".join(f"{campo} = %s" for campo in permitidos)
    conn = get_conn()
    with conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM pacientes WHERE codigo = %s", (codigo,))
            if cur.fetchone() is None:
                return None
            cur.execute(
                f"UPDATE pacientes SET {asignaciones} WHERE codigo = %s",
                [*permitidos.values(), codigo],
            )
            cur.execute("SELECT * FROM pacientes WHERE codigo = %s", (codigo,))
            fila = cur.fetchone()
        conn.commit()
    return _normalizar(fila)


def eliminar(codigo: str) -> bool:
    """Devuelve True si borro algo, False si el codigo no existia."""
    conn = get_conn()
    with conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM pacientes WHERE codigo = %s", (codigo,))
            borrados = cur.rowcount
        conn.commit()
    return borrados > 0
