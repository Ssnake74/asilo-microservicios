"""
Capa de acceso a datos del microservicio de Pacientes (ancianos internos).

Es la unica parte del microservicio que habla directamente con la base de
datos, igual que en los otros dos servicios del sistema.
"""

import os
import sqlite3

DB_PATH = os.getenv("DB_PATH", "pacientes.db")


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS pacientes (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo              TEXT    NOT NULL UNIQUE,   -- PAC-001
    nombres             TEXT    NOT NULL,
    apellidos           TEXT    NOT NULL,
    dpi                 TEXT,
    fecha_nacimiento    TEXT    NOT NULL,          -- AAAA-MM-DD
    sexo                TEXT    NOT NULL,          -- M | F
    tipo_sangre         TEXT,
    fecha_ingreso       TEXT    NOT NULL,          -- AAAA-MM-DD
    habitacion          TEXT,
    procedencia         TEXT,
    familiar_nombre     TEXT    NOT NULL,
    familiar_parentesco TEXT,
    familiar_telefono   TEXT    NOT NULL,
    familiar_email      TEXT,
    padecimientos       TEXT,
    alergias            TEXT,
    cubierto_fundacion  INTEGER NOT NULL DEFAULT 1,
    estado              TEXT    NOT NULL DEFAULT 'ACTIVO',  -- ACTIVO | EGRESADO | FALLECIDO
    fecha_registro      TEXT    NOT NULL
);
"""


def init_db() -> None:
    conn = get_conn()
    with conn:
        conn.executescript(SCHEMA)
    conn.close()


def siguiente_codigo(conn: sqlite3.Connection) -> str:
    """Genera el siguiente codigo correlativo del asilo: PAC-001, PAC-002..."""
    fila = conn.execute(
        "SELECT codigo FROM pacientes ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if fila is None:
        return "PAC-001"
    try:
        ultimo = int(fila["codigo"].split("-")[-1])
    except ValueError:
        ultimo = conn.execute("SELECT COUNT(*) AS n FROM pacientes").fetchone()["n"]
    return f"PAC-{ultimo + 1:03d}"
