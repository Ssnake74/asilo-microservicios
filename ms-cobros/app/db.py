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
    # Con DB_SSL_CA la conexion va cifrada y se verifica el certificado del
    # servidor. En Azure es obligatorio; en desarrollo queda sin definir.
    "ssl_ca": os.getenv("DB_SSL_CA") or None,
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
# La llave foranea impide crear un cargo hacia una tarifa que no existe
# y borrar una tarifa que ya tenga cargos (ON DELETE RESTRICT).
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
    fecha_pago          DATETIME      NULL,
    INDEX idx_paciente (paciente_id),
    INDEX idx_estado (estado),
    INDEX idx_fecha (fecha),
    CONSTRAINT fk_cargo_tarifa FOREIGN KEY (tarifa_id)
        REFERENCES tarifas (id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""

# ---------------------------------------------------------------------
# Entradas y salidas del asilo (seccion 17.3 del ERS, mas los pagos a la
# fundacion). Ninguna tiene llave foranea: la cuota apunta al interno de
# otro esquema, y donaciones, gastos y pagos no dependen de nada.
#
# Una cuota por interno y por mes: el UNIQUE lo impone el motor, aunque
# dos personas de caja generen las cuotas del mes al mismo tiempo.
# ---------------------------------------------------------------------

SCHEMA_FINANZAS = [
    """
    CREATE TABLE IF NOT EXISTS cuotas_mensuales (
        id               INT AUTO_INCREMENT PRIMARY KEY,
        paciente_id      VARCHAR(40)   NOT NULL,
        paciente_nombre  VARCHAR(120)  NOT NULL,
        familiar_email   VARCHAR(120)  NULL,
        periodo          CHAR(7)       NOT NULL,
        monto            DECIMAL(10,2) NOT NULL,
        estado           VARCHAR(12)   NOT NULL DEFAULT 'PENDIENTE',
        fecha_registro   DATETIME      NOT NULL,
        fecha_pago       DATETIME      NULL,
        UNIQUE KEY uq_cuota_mes (paciente_id, periodo),
        INDEX idx_periodo (periodo)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS donaciones (
        id            INT AUTO_INCREMENT PRIMARY KEY,
        origen        VARCHAR(120)  NOT NULL,
        tipo_donante  VARCHAR(30)   NOT NULL,
        monto         DECIMAL(10,2) NOT NULL,
        fecha         DATE          NOT NULL,
        descripcion   VARCHAR(300)  NULL,
        INDEX idx_fecha (fecha)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS gastos (
        id           INT AUTO_INCREMENT PRIMARY KEY,
        categoria    VARCHAR(30)   NOT NULL,
        monto        DECIMAL(10,2) NOT NULL,
        fecha        DATE          NOT NULL,
        descripcion  VARCHAR(300)  NOT NULL,
        comprobante  VARCHAR(60)   NULL,
        INDEX idx_fecha (fecha)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS pagos_fundacion (
        id           INT AUTO_INCREMENT PRIMARY KEY,
        monto        DECIMAL(10,2) NOT NULL,
        fecha        DATE          NOT NULL,
        descripcion  VARCHAR(300)  NULL,
        comprobante  VARCHAR(60)   NULL,
        INDEX idx_fecha (fecha)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
]

# Tarifas iniciales para poder demostrar el sistema sin cargar datos a mano.
TARIFAS_SEMILLA = [
    ("Consulta con médico general", "CITA", "75.00", "60.00"),
    ("Consulta con médico especialista", "CITA", "250.00", "40.00"),
    ("Hematología completa", "EXAMEN", "120.00", "50.00"),
    ("Glucosa en ayunas", "EXAMEN", "60.00", "50.00"),
    ("Radiografía de tórax", "EXAMEN", "300.00", "30.00"),
    ("Losartán 50 mg (caja)", "MEDICAMENTO", "85.00", "25.00"),
    ("Acetaminofén 500 mg (caja)", "MEDICAMENTO", "40.00", "25.00"),
]

# Las bases sembradas antes guardaron estos conceptos sin tildes. Se
# corrigen al arrancar, en el tarifario y en los cargos que los copiaron.
# utf8mb4_bin compara letra por letra: con la intercalacion de la tabla,
# «medico» y «médico» serian iguales y no se sabria cuales faltan.
CONCEPTOS_SIN_TILDE = [
    ("Consulta con medico general", "Consulta con médico general"),
    ("Consulta con medico especialista", "Consulta con médico especialista"),
    ("Hematologia completa", "Hematología completa"),
    ("Radiografia de torax", "Radiografía de tórax"),
    ("Losartan 50 mg (caja)", "Losartán 50 mg (caja)"),
    ("Acetaminofen 500 mg (caja)", "Acetaminofén 500 mg (caja)"),
]

CAMPOS_TARIFA_ACTUALIZABLES = {
    "concepto", "tipo", "precio", "descuento_fundacion", "activo",
}


def init_db(intentos: int = 15, espera: float = 3.0) -> None:
    """
    Crea las tablas y siembra el tarifario, esperando a que MySQL responda.
    Reintenta porque MySQL tarda mas que este contenedor en aceptar conexiones.
    """
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
                    for tabla in SCHEMA_FINANZAS:
                        cur.execute(tabla)
                    # El dia del pago lo pide el informe de ingresos (RF-41).
                    # Los cargos pagados antes de que existiera la columna
                    # quedan con NULL y el informe usa la fecha del cargo.
                    cur.execute(
                        """SELECT COUNT(*) AS n FROM information_schema.COLUMNS
                           WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'cargos'
                             AND COLUMN_NAME = 'fecha_pago'"""
                    )
                    if cur.fetchone()["n"] == 0:
                        cur.execute("ALTER TABLE cargos ADD COLUMN fecha_pago DATETIME NULL AFTER fecha")
                        print("[ms-cobros] Columna fecha_pago agregada a cargos.", flush=True)
                    cur.execute("SELECT COUNT(*) AS n FROM tarifas")
                    if cur.fetchone()["n"] == 0:
                        cur.executemany(
                            """INSERT INTO tarifas (concepto, tipo, precio, descuento_fundacion)
                               VALUES (%s, %s, %s, %s)""",
                            TARIFAS_SEMILLA,
                        )
                    corregidos = 0
                    for viejo, nuevo in CONCEPTOS_SIN_TILDE:
                        for tabla in ("tarifas", "cargos"):
                            corregidos += cur.execute(
                                f"UPDATE {tabla} SET concepto = %s "
                                "WHERE concepto COLLATE utf8mb4_bin = %s",
                                (nuevo, viejo),
                            )
                    if corregidos:
                        print(f"[ms-cobros] Conceptos con tilde corregidos: {corregidos}.", flush=True)
                conn.commit()
            print(f"[ms-cobros] Conectado a MySQL en el intento {intento}.", flush=True)
            return
        except pymysql.err.OperationalError as error:
            ultimo_error = error
            print(f"[ms-cobros] MySQL aun no responde ({intento}/{intentos}).", flush=True)
            time.sleep(espera)
    raise RuntimeError(f"No se pudo conectar a MySQL: {ultimo_error}")


def _normalizar(fila: dict | None) -> dict | None:
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
            cur.execute(
                "UPDATE cargos SET estado = 'PAGADO', fecha_pago = %s WHERE id = %s",
                (datetime.now().replace(microsecond=0), cargo_id),
            )
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

    # La resta va en Decimal, antes de pasar los totales a float (RNF-15).
    saldo = totales["total_neto"] - totales["total_pagado"]
    resultado = _normalizar(totales)
    resultado["saldo_pendiente"] = float(saldo)
    resultado["paciente_nombre"] = identidad["paciente_nombre"] if identidad else None
    resultado["familiar_email"] = identidad["familiar_email"] if identidad else None
    return resultado


# =====================================================================
# Cuotas mensuales (RF-33)
# =====================================================================

class CuotaRepetida(Exception):
    """Ese interno ya tiene la cuota de ese mes."""


def listar_cuotas(periodo: str | None = None, paciente_id: str | None = None,
                  estado: str | None = None) -> list[dict]:
    sql = "SELECT * FROM cuotas_mensuales WHERE 1 = 1"
    params: list = []
    for campo, valor in (("periodo", periodo), ("paciente_id", paciente_id), ("estado", estado)):
        if valor:
            sql += f" AND {campo} = %s"
            params.append(valor.upper() if campo == "estado" else valor)
    sql += " ORDER BY periodo DESC, paciente_nombre"
    conn = get_conn()
    with conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return [_normalizar(f) for f in cur.fetchall()]


def obtener_cuota(cuota_id: int) -> dict | None:
    conn = get_conn()
    with conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM cuotas_mensuales WHERE id = %s", (cuota_id,))
            return _normalizar(cur.fetchone())


def crear_cuotas(periodo: str, monto: str, internos: list[dict]) -> tuple[list[int], int]:
    """
    Crea la cuota del mes a cada interno que todavia no la tenga. Devuelve
    los id creados y cuantos ya la tenian; los que ya la tenian no cambian.
    """
    creadas, repetidas = [], 0
    ahora = datetime.now().replace(microsecond=0)
    conn = get_conn()
    with conn:
        with conn.cursor() as cur:
            for interno in internos:
                filas = cur.execute(
                    """INSERT IGNORE INTO cuotas_mensuales
                       (paciente_id, paciente_nombre, familiar_email, periodo, monto, estado, fecha_registro)
                       VALUES (%s, %s, %s, %s, %s, 'PENDIENTE', %s)""",
                    (interno["paciente_id"], interno["paciente_nombre"], interno.get("familiar_email"),
                     periodo, monto, ahora),
                )
                if filas:
                    creadas.append(cur.lastrowid)
                else:
                    repetidas += 1
        conn.commit()
    return creadas, repetidas


def pagar_cuota(cuota_id: int) -> bool:
    """False si la cuota ya estaba pagada: nunca se cobra dos veces."""
    conn = get_conn()
    with conn:
        with conn.cursor() as cur:
            cambiadas = cur.execute(
                """UPDATE cuotas_mensuales SET estado = 'PAGADA', fecha_pago = %s
                   WHERE id = %s AND estado = 'PENDIENTE'""",
                (datetime.now().replace(microsecond=0), cuota_id),
            )
        conn.commit()
    return cambiadas > 0


def anular_cuota(cuota_id: int) -> bool:
    """Solo una pendiente: una cuota pagada es dinero que ya entro."""
    conn = get_conn()
    with conn:
        with conn.cursor() as cur:
            borradas = cur.execute(
                "DELETE FROM cuotas_mensuales WHERE id = %s AND estado = 'PENDIENTE'", (cuota_id,)
            )
        conn.commit()
    return borradas > 0


# =====================================================================
# Donaciones, gastos y pagos a la fundacion (RF-34 a RF-36)
#
# Las tres tablas tienen la misma forma de consulta: por rango de fechas,
# de la mas reciente a la mas vieja.
# =====================================================================

COLUMNAS = {
    "donaciones": ("origen", "tipo_donante", "monto", "fecha", "descripcion"),
    "gastos": ("categoria", "monto", "fecha", "descripcion", "comprobante"),
    "pagos_fundacion": ("monto", "fecha", "descripcion", "comprobante"),
}


def registrar(tabla: str, datos: dict) -> dict:
    columnas = COLUMNAS[tabla]
    conn = get_conn()
    with conn:
        with conn.cursor() as cur:
            cur.execute(
                f"INSERT INTO {tabla} ({', '.join(columnas)}) VALUES ({', '.join(['%s'] * len(columnas))})",
                tuple(datos.get(c) for c in columnas),
            )
            nuevo = cur.lastrowid
            cur.execute(f"SELECT * FROM {tabla} WHERE id = %s", (nuevo,))
            fila = cur.fetchone()
        conn.commit()
    return _normalizar(fila)


def listar(tabla: str, desde: str | None = None, hasta: str | None = None) -> list[dict]:
    if tabla not in COLUMNAS:
        raise ValueError(tabla)
    sql = f"SELECT * FROM {tabla} WHERE 1 = 1"
    params: list = []
    if desde:
        sql += " AND fecha >= %s"
        params.append(desde)
    if hasta:
        sql += " AND fecha <= %s"
        params.append(hasta)
    sql += " ORDER BY fecha DESC, id DESC"
    conn = get_conn()
    with conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return [_normalizar(f) for f in cur.fetchall()]


def deuda_con_la_fundacion() -> dict:
    """
    Las sumas las hace MySQL en DECIMAL; la resta del saldo la hace
    reglas.py en Decimal, antes de pasar a float (RNF-15).
    """
    conn = get_conn()
    with conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT
                       COALESCE(SUM(monto_neto), 0) AS total_servicios,
                       COALESCE(SUM(CASE WHEN tipo = 'CITA' THEN monto_neto END), 0) AS consultas,
                       COALESCE(SUM(CASE WHEN tipo = 'EXAMEN' THEN monto_neto END), 0) AS examenes,
                       COALESCE(SUM(CASE WHEN tipo = 'MEDICAMENTO' THEN monto_neto END), 0) AS medicamentos,
                       COALESCE(SUM(tipo = 'CITA' AND estado = 'PENDIENTE'), 0) AS citas_por_cobrar
                   FROM cargos"""
            )
            totales = cur.fetchone()
            cur.execute("SELECT COALESCE(SUM(monto), 0) AS pagado FROM pagos_fundacion")
            totales["total_pagado"] = cur.fetchone()["pagado"]
    return totales
