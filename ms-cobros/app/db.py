"""
Capa de Acceso a Datos del microservicio de Cobros.

Corresponde a la "Capa de Acceso a Datos (Repositorio)" del documento de
Estructura de Capas. Es el unico archivo del servicio que contiene SQL.

Dos cosas que este servicio hace distinto a ms-pacientes, porque aqui se
maneja dinero:

  1. Los montos son DECIMAL(10,2), no REAL. DECIMAL guarda el numero
     exacto; REAL es punto flotante y arrastra error al sumar.

  2. Los totales del estado de cuenta se calculan con SUM() en MySQL, no
     sumando en Python. Asi la suma tambien ocurre en DECIMAL, y ademas
     el motor recorre la tabla una sola vez.
"""

import os
import time
from datetime import date, datetime
from decimal import Decimal

import pymysql
from pymysql.cursors import DictCursor

CONFIG = {
    "host": os.getenv("DB_HOST", "mysql"),
    "port": int(os.getenv("DB_PORT", "3306")),
    "user": os.getenv("DB_USER", "u_cobros"),
    "password": os.getenv("DB_PASSWORD", "cobros_2026"),
    "database": os.getenv("DB_NAME", "asilo_cobros"),
    "charset": "utf8mb4",
    "cursorclass": DictCursor,
}


def get_conn() -> pymysql.connections.Connection:
    return pymysql.connect(**CONFIG)


# ---------------------------------------------------------------------
# Esquema
#
# DECIMAL(10,2)  -> hasta 8 digitos enteros y 2 decimales. Alcanza para
#                   Q99,999,999.99, de sobra para el asilo.
# DECIMAL(5,2)   -> el porcentaje de descuento: 0.00 a 100.00.
#
# La llave foranea ahora si se cumple siempre. InnoDB no permite crear
# un cargo apuntando a una tarifa que no existe, ni borrar una tarifa
# que ya tenga cargos (ON DELETE RESTRICT). En SQLite esa restriccion
# dependia de encender un PRAGMA en cada conexion.
# ---------------------------------------------------------------------

SCHEMA_TARIFAS = """
CREATE TABLE IF NOT EXISTS tarifas (
    id                  INT AUTO_INCREMENT PRIMARY KEY,
    concepto            VARCHAR(120)  NOT NULL,
    tipo                VARCHAR(12)   NOT NULL,
    precio              DECIMAL(10,2) NOT NULL,
    descuento_fundacion DECIMAL(5,2)  NOT NULL DEFAULT 0.00,
    activo              BOOLEAN       NOT NULL DEFAULT TRUE,
    INDEX idx_tipo (tipo)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""

SCHEMA_CARGOS = """
CREATE TABLE IF NOT EXISTS cargos (
    id                  INT AUTO_INCREMENT PRIMARY KEY,
    paciente_id         VARCHAR(40)   NOT NULL,
    paciente_nombre     VARCHAR(160)  NULL,
    familiar_email      VARCHAR(120)  NULL,
    tarifa_id           INT           NOT NULL,
    concepto            VARCHAR(120)  NOT NULL,
    tipo                VARCHAR(12)   NOT NULL,
    cantidad            INT           NOT NULL DEFAULT 1,
    monto_bruto         DECIMAL(10,2) NOT NULL,
    descuento_aplicado  DECIMAL(10,2) NOT NULL,
    monto_neto          DECIMAL(10,2) NOT NULL,
    cubierto_fundacion  BOOLEAN       NOT NULL DEFAULT FALSE,
    estado              VARCHAR(12)   NOT NULL DEFAULT 'PENDIENTE',
    referencia          VARCHAR(60)   NULL,
    fecha               DATETIME      NOT NULL,
    INDEX idx_paciente (paciente_id),
    INDEX idx_estado (estado),
    INDEX idx_fecha (fecha),
    CONSTRAINT fk_cargo_tarifa FOREIGN KEY (tarifa_id)
        REFERENCES tarifas (id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""

# Tarifas iniciales para poder demostrar el sistema sin cargar datos a mano.
TARIFAS_SEMILLA = [
    ("Consulta con medico general", "CITA", "75.00", "60.00"),
    ("Consulta con medico especialista", "CITA", "250.00", "40.00"),
    ("Hematologia completa", "EXAMEN", "120.00", "50.00"),
    ("Glucosa en ayunas", "EXAMEN", "60.00", "50.00"),
    ("Radiografia de torax", "EXAMEN", "300.00", "30.00"),
    ("Losartan 50 mg (caja)", "MEDICAMENTO", "85.00", "25.00"),
    ("Acetaminofen 500 mg (caja)", "MEDICAMENTO", "40.00", "25.00"),
]

CAMPOS_TARIFA_ACTUALIZABLES = {
    "concepto", "tipo", "precio", "descuento_fundacion", "activo",
}


def init_db(intentos: int = 15, espera: float = 3.0) -> None:
    """Crea las tablas y siembra el tarifario, esperando a que MySQL responda."""
    ultimo_error = None
    for intento in range(1, intentos + 1):
        try:
            conn = get_conn()
            with conn:
                with conn.cursor() as cur:
                    # Las tablas se crean en orden: tarifas primero,
                    # porque cargos tiene una llave foranea hacia ella.
                    cur.execute(SCHEMA_TARIFAS)
                    cur.execute(SCHEMA_CARGOS)
                    cur.execute("SELECT COUNT(*) AS n FROM tarifas")
                    if cur.fetchone()["n"] == 0:
                        cur.executemany(
                            """INSERT INTO tarifas (concepto, tipo, precio, descuento_fundacion)
                               VALUES (%s, %s, %s, %s)""",
                            TARIFAS_SEMILLA,
                        )
                conn.commit()
            print(f"[ms-cobros] Conectado a MySQL en el intento {intento}.", flush=True)
            return
        except pymysql.err.OperationalError as error:
            ultimo_error = error
            print(f"[ms-cobros] MySQL aun no responde ({intento}/{intentos}).", flush=True)
            time.sleep(espera)
    raise RuntimeError(f"No se pudo conectar a MySQL: {ultimo_error}")


def _normalizar(fila: dict | None) -> dict | None:
    """
    Traduce los tipos de MySQL a los que espera Pydantic.

    Los DECIMAL llegan como objetos Decimal. Se convierten a float aqui,
    en la frontera de salida, porque el JSON de la API y la pantalla
    trabajan con numeros normales. Lo importante es que el guardado y
    las sumas ya ocurrieron en Decimal: la conversion a float es solo
    para mostrar.
    """
    if fila is None:
        return None
    limpia = dict(fila)
    for campo, valor in limpia.items():
        if isinstance(valor, Decimal):
            limpia[campo] = float(valor)
        elif isinstance(valor, datetime):
            limpia[campo] = valor.isoformat(sep=" ", timespec="seconds")
        elif isinstance(valor, date):
            limpia[campo] = valor.isoformat()
    for booleano in ("activo", "cubierto_fundacion"):
        if booleano in limpia:
            limpia[booleano] = bool(limpia[booleano])
    return limpia


# =====================================================================
# Tarifas
# =====================================================================

def contar_tarifas() -> int:
    conn = get_conn()
    with conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM tarifas")
            return cur.fetchone()["n"]


def listar_tarifas(tipo: str | None = None, solo_activas: bool = False) -> list[dict]:
    sql = "SELECT * FROM tarifas WHERE 1 = 1"
    params: list = []
    if tipo:
        sql += " AND tipo = %s"
        params.append(tipo.upper())
    if solo_activas:
        sql += " AND activo = TRUE"
    sql += " ORDER BY tipo, concepto"

    conn = get_conn()
    with conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return [_normalizar(f) for f in cur.fetchall()]


def obtener_tarifa(tarifa_id: int) -> dict | None:
    conn = get_conn()
    with conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM tarifas WHERE id = %s", (tarifa_id,))
            return _normalizar(cur.fetchone())


def buscar_tarifa_para_cargo(tarifa_id: int | None, tipo: str) -> dict | None:
    """
    Devuelve la tarifa activa que corresponde al cargo.

    Si viene tarifa_id se usa esa; si no, se toma la mas barata del tipo
    solicitado. Asi ms-solicitudes puede pedir "una CITA" sin conocer
    los ids del tarifario.
    """
    conn = get_conn()
    with conn:
        with conn.cursor() as cur:
            if tarifa_id is not None:
                cur.execute(
                    "SELECT * FROM tarifas WHERE id = %s AND activo = TRUE", (tarifa_id,)
                )
            else:
                cur.execute(
                    """SELECT * FROM tarifas WHERE tipo = %s AND activo = TRUE
                       ORDER BY precio LIMIT 1""",
                    (tipo,),
                )
            return _normalizar(cur.fetchone())


def crear_tarifa(datos: dict) -> dict:
    conn = get_conn()
    with conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO tarifas (concepto, tipo, precio, descuento_fundacion, activo)
                   VALUES (%s, %s, %s, %s, %s)""",
                (
                    datos["concepto"], datos["tipo"], datos["precio"],
                    datos["descuento_fundacion"], datos["activo"],
                ),
            )
            nuevo_id = cur.lastrowid
            cur.execute("SELECT * FROM tarifas WHERE id = %s", (nuevo_id,))
            fila = cur.fetchone()
        conn.commit()
    return _normalizar(fila)


def actualizar_tarifa(tarifa_id: int, cambios: dict) -> dict | None:
    permitidos = {k: v for k, v in cambios.items() if k in CAMPOS_TARIFA_ACTUALIZABLES}
    if not permitidos:
        return None
    asignaciones = ", ".join(f"{campo} = %s" for campo in permitidos)

    conn = get_conn()
    with conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM tarifas WHERE id = %s", (tarifa_id,))
            if cur.fetchone() is None:
                return None
            cur.execute(
                f"UPDATE tarifas SET {asignaciones} WHERE id = %s",
                [*permitidos.values(), tarifa_id],
            )
            cur.execute("SELECT * FROM tarifas WHERE id = %s", (tarifa_id,))
            fila = cur.fetchone()
        conn.commit()
    return _normalizar(fila)


def tarifa_tiene_cargos(tarifa_id: int) -> bool:
    conn = get_conn()
    with conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM cargos WHERE tarifa_id = %s", (tarifa_id,))
            return cur.fetchone()["n"] > 0


def eliminar_tarifa(tarifa_id: int) -> bool:
    conn = get_conn()
    with conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM tarifas WHERE id = %s", (tarifa_id,))
            borradas = cur.rowcount
        conn.commit()
    return borradas > 0


# =====================================================================
# Cargos
# =====================================================================

def crear_cargo(datos: dict, tarifa: dict, montos: dict) -> dict:
    """
    Guarda el cargo ya calculado.

    Los montos llegan como Decimal desde reglas.py y se entregan asi a
    MySQL: no pasan por float en ningun momento del camino.
    """
    conn = get_conn()
    with conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO cargos (
                       paciente_id, paciente_nombre, familiar_email, tarifa_id, concepto,
                       tipo, cantidad, monto_bruto, descuento_aplicado, monto_neto,
                       cubierto_fundacion, estado, referencia, fecha)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'PENDIENTE', %s, %s)""",
                (
                    datos["paciente_id"], datos["paciente_nombre"], datos["familiar_email"],
                    tarifa["id"], tarifa["concepto"], tarifa["tipo"], datos["cantidad"],
                    montos["monto_bruto"], montos["descuento_aplicado"], montos["monto_neto"],
                    datos["cubierto_fundacion"], datos["referencia"],
                    datetime.now().replace(microsecond=0),
                ),
            )
            nuevo_id = cur.lastrowid
            cur.execute("SELECT * FROM cargos WHERE id = %s", (nuevo_id,))
            fila = cur.fetchone()
        conn.commit()
    return _normalizar(fila)


def listar_cargos(paciente_id: str | None = None, estado: str | None = None) -> list[dict]:
    sql = "SELECT * FROM cargos WHERE 1 = 1"
    params: list = []
    if paciente_id:
        sql += " AND paciente_id = %s"
        params.append(paciente_id)
    if estado:
        sql += " AND estado = %s"
        params.append(estado.upper())
    sql += " ORDER BY id DESC"

    conn = get_conn()
    with conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return [_normalizar(f) for f in cur.fetchall()]


def obtener_cargo(cargo_id: int) -> dict | None:
    conn = get_conn()
    with conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM cargos WHERE id = %s", (cargo_id,))
            return _normalizar(cur.fetchone())


def marcar_pagado(cargo_id: int) -> dict | None:
    conn = get_conn()
    with conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE cargos SET estado = 'PAGADO' WHERE id = %s", (cargo_id,))
            cur.execute("SELECT * FROM cargos WHERE id = %s", (cargo_id,))
            fila = cur.fetchone()
        conn.commit()
    return _normalizar(fila)


def eliminar_cargo(cargo_id: int) -> bool:
    conn = get_conn()
    with conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM cargos WHERE id = %s", (cargo_id,))
            borrados = cur.rowcount
        conn.commit()
    return borrados > 0


def totales_paciente(paciente_id: str) -> dict:
    """
    Calcula el corte de cuenta con SUM() de MySQL.

    Se hace en la base y no en Python por dos razones: la suma ocurre en
    DECIMAL (exacta), y el motor recorre la tabla una sola vez en lugar
    de traer todas las filas para sumarlas afuera. Cuando lleguen los
    reportes por rango de fecha, este es el camino que vamos a seguir.

    COALESCE devuelve 0 cuando no hay cargos, porque SUM() sobre cero
    filas devuelve NULL, no cero.
    """
    conn = get_conn()
    with conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT
                       COUNT(*)                        AS cantidad_cargos,
                       COALESCE(SUM(monto_bruto), 0)        AS total_bruto,
                       COALESCE(SUM(descuento_aplicado), 0) AS total_descuento_fundacion,
                       COALESCE(SUM(monto_neto), 0)         AS total_neto,
                       COALESCE(SUM(CASE WHEN estado = 'PAGADO'
                                         THEN monto_neto ELSE 0 END), 0) AS total_pagado
                   FROM cargos WHERE paciente_id = %s""",
                (paciente_id,),
            )
            totales = cur.fetchone()

            # Datos del paciente tomados del cargo mas reciente.
            cur.execute(
                """SELECT paciente_nombre, familiar_email FROM cargos
                   WHERE paciente_id = %s ORDER BY id DESC LIMIT 1""",
                (paciente_id,),
            )
            identidad = cur.fetchone()

    resultado = _normalizar(totales)
    resultado["saldo_pendiente"] = round(
        resultado["total_neto"] - resultado["total_pagado"], 2
    )
    resultado["paciente_nombre"] = identidad["paciente_nombre"] if identidad else None
    resultado["familiar_email"] = identidad["familiar_email"] if identidad else None
    return resultado
