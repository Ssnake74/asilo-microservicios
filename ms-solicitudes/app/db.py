"""
Capa de acceso a datos del microservicio de Solicitudes y Visitas Medicas.

Este microservicio tiene su propia base de datos, independiente de la del
microservicio de Cobros: si uno se cae, el otro sigue funcionando.
"""

import os
import sqlite3

DB_PATH = os.getenv("DB_PATH", "solicitudes.db")


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS solicitudes (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    paciente_id           TEXT    NOT NULL,
    paciente_nombre       TEXT    NOT NULL,
    familiar_email        TEXT,
    medico_general        TEXT    NOT NULL,
    especialidad_remitida TEXT    NOT NULL,
    motivo                TEXT    NOT NULL,
    cubierto_fundacion    INTEGER NOT NULL DEFAULT 1,
    estado                TEXT    NOT NULL DEFAULT 'PENDIENTE',  -- PENDIENTE | CONVERTIDA | ANULADA
    fecha_solicitud       TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS visitas (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    solicitud_id    INTEGER NOT NULL UNIQUE,
    paciente_id     TEXT    NOT NULL,
    paciente_nombre TEXT    NOT NULL,
    medico_tratante TEXT    NOT NULL,
    especialidad    TEXT    NOT NULL,
    fecha_visita    TEXT    NOT NULL,
    observaciones   TEXT,
    cargo_id        INTEGER,
    cargo_generado  INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (solicitud_id) REFERENCES solicitudes (id)
);
"""


def init_db() -> None:
    conn = get_conn()
    with conn:
        conn.executescript(SCHEMA)
    conn.close()
