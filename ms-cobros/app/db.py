"""
Capa de acceso a datos del microservicio de Cobros.

Corresponde a la "Capa de Acceso a Datos (Repositorio)" descrita en el
documento de Estructura de Capas del proyecto: es la unica parte del
microservicio que habla directamente con el motor de base de datos.
"""

import os
import sqlite3

# Cada microservicio tiene su PROPIA base de datos (patron database-per-service).
# En Docker esta ruta apunta a un volumen persistente.
DB_PATH = os.getenv("DB_PATH", "cobros.db")


def get_conn() -> sqlite3.Connection:
    """Devuelve una conexion con filas accesibles por nombre de columna."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS tarifas (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    concepto            TEXT    NOT NULL,
    tipo                TEXT    NOT NULL,          -- CITA | EXAMEN | MEDICAMENTO
    precio              REAL    NOT NULL,
    descuento_fundacion REAL    NOT NULL DEFAULT 0, -- porcentaje 0-100
    activo              INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS cargos (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    paciente_id         TEXT    NOT NULL,
    paciente_nombre     TEXT,
    familiar_email      TEXT,
    tarifa_id           INTEGER NOT NULL,
    concepto            TEXT    NOT NULL,
    tipo                TEXT    NOT NULL,
    cantidad            INTEGER NOT NULL DEFAULT 1,
    monto_bruto         REAL    NOT NULL,
    descuento_aplicado  REAL    NOT NULL,
    monto_neto          REAL    NOT NULL,
    cubierto_fundacion  INTEGER NOT NULL DEFAULT 0,
    estado              TEXT    NOT NULL DEFAULT 'PENDIENTE',  -- PENDIENTE | PAGADO
    referencia          TEXT,
    fecha               TEXT    NOT NULL,
    FOREIGN KEY (tarifa_id) REFERENCES tarifas (id)
);
"""

# Tarifas iniciales para poder demostrar el sistema sin cargar datos a mano.
TARIFAS_SEMILLA = [
    ("Consulta con medico general", "CITA", 75.00, 60.0),
    ("Consulta con medico especialista", "CITA", 250.00, 40.0),
    ("Hematologia completa", "EXAMEN", 120.00, 50.0),
    ("Glucosa en ayunas", "EXAMEN", 60.00, 50.0),
    ("Radiografia de torax", "EXAMEN", 300.00, 30.0),
    ("Losartan 50 mg (caja)", "MEDICAMENTO", 85.00, 25.0),
    ("Acetaminofen 500 mg (caja)", "MEDICAMENTO", 40.00, 25.0),
]


def init_db() -> None:
    """Crea las tablas si no existen y siembra las tarifas base."""
    conn = get_conn()
    with conn:
        conn.executescript(SCHEMA)
        total = conn.execute("SELECT COUNT(*) AS n FROM tarifas").fetchone()["n"]
        if total == 0:
            conn.executemany(
                """INSERT INTO tarifas (concepto, tipo, precio, descuento_fundacion)
                   VALUES (?, ?, ?, ?)""",
                TARIFAS_SEMILLA,
            )
    conn.close()
