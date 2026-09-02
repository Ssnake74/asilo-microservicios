"""
Capa de Acceso a Datos del Gateway.

Guarda dos cosas en el esquema asilo_gateway:

  usuarios  quien puede entrar y con que rol
  sesiones  que tokens estan activos en este momento

Guardar las sesiones en la base y no solo en memoria tiene una ventaja
concreta: si el gateway se reinicia, nadie pierde la sesion. Y permite
cerrar sesion de verdad, borrando la fila, cosa que un token firmado
tipo JWT no permite sin trabajo extra.
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
                    cur.execute(TABLA_USUARIOS)
                    cur.execute(TABLA_SESIONES)
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
