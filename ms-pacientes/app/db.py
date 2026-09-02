"""
Capa de Acceso a Datos del microservicio de Pacientes.

Corresponde a la "Capa de Acceso a Datos (Repositorio)" del documento de
Estructura de Capas del proyecto. Este archivo es el UNICO del servicio
que contiene SQL y el unico que sabe que el motor es MySQL.

main.py ya no escribe consultas: llama a funciones con nombre
(crear, obtener_por_codigo, actualizar...). Eso es lo que hace que esto
sea un repositorio y no solo "un archivo con la conexion".

Ventaja practica: si manana el servidor de la universidad usa SQL Server
u Oracle en vez de MySQL, se reescribe este archivo y nada mas.
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
# docker-compose.yml. Nunca se escriben aqui: asi la misma imagen sirve
# para su maquina y para el servidor de la universidad.
# ---------------------------------------------------------------------

CONFIG = {
    "host": os.getenv("DB_HOST", "mysql"),
    "port": int(os.getenv("DB_PORT", "3306")),
    "user": os.getenv("DB_USER", "u_pacientes"),
    "password": os.getenv("DB_PASSWORD", "pacientes_2026"),
    "database": os.getenv("DB_NAME", "asilo_pacientes"),
    "charset": "utf8mb4",
    "cursorclass": DictCursor,
}


def get_conn() -> pymysql.connections.Connection:
    """Abre una conexion nueva a MySQL."""
    return pymysql.connect(**CONFIG)


# ---------------------------------------------------------------------
# Esquema
#
# Diferencias frente a la version en SQLite, que son las mismas que
# vamos a encontrar en los otros dos servicios:
#
#   AUTOINCREMENT      ->  AUTO_INCREMENT
#   TEXT               ->  VARCHAR(n), con el largo declarado
#   TEXT con fecha     ->  DATE / DATETIME de verdad
#   INTEGER 0 o 1      ->  BOOLEAN
#
# Declarar el largo de cada VARCHAR obliga a pensar cuanto mide cada
# dato, y MySQL rechaza lo que no quepa en vez de guardarlo cortado.
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
}


def init_db(intentos: int = 15, espera: float = 3.0) -> None:
    """
    Crea la tabla si no existe, esperando a que MySQL este disponible.

    El reintento no es adorno: Docker levanta este contenedor y el de
    MySQL casi al mismo tiempo, y MySQL tarda mas en aceptar conexiones.
    Sin este bucle, el servicio se cae al arrancar la primera vez.
    """
    ultimo_error = None
    for intento in range(1, intentos + 1):
        try:
            conn = get_conn()
            with conn:
                with conn.cursor() as cur:
                    cur.execute(SCHEMA)
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
# MySQL devuelve tipos de Python de verdad: DATE llega como date,
# DATETIME como datetime y BOOLEAN como 0 o 1. Los modelos de schemas.py
# esperan texto y booleanos, asi que se convierte aqui, en la frontera
# de la capa de datos, y no en cada endpoint.
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

    El codigo se arma DESPUES del INSERT, a partir del id que genero
    MySQL: PAC-001, PAC-002... Es mas seguro que el "buscar el ultimo y
    sumarle uno" de la version anterior, porque ahi dos altas
    simultaneas podian calcular el mismo numero. Aqui el id lo entrega
    el motor y no se repite nunca.

    El INSERT y el UPDATE del codigo van en la MISMA transaccion: si
    algo falla a medias, no queda un registro sin codigo.
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
    nunca concatenados: eso es lo que evita la inyeccion SQL.
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
