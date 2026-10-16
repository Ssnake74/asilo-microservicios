"""
Capa de Acceso a Datos del microservicio de Catalogo (esquema asilo_catalogo).

Es el unico archivo del servicio con SQL. Los cinco recursos del catalogo
tienen la misma forma -nombre, algun dato propio y si esta activo- y por
eso comparten las funciones de abajo, que reciben el nombre del recurso.
"""

import os
import time

import httpx
import pymysql
from pymysql.cursors import DictCursor

from .reglas import clave_de_comparacion

CONFIG = {
    "host": os.getenv("DB_HOST", "mysql"),
    "port": int(os.getenv("DB_PORT", "3306")),
    "user": os.getenv("DB_USER", "u_catalogo"),
    "password": os.getenv("DB_PASSWORD", "catalogo_2026"),
    "database": os.getenv("DB_NAME", "asilo_catalogo"),
    "charset": "utf8mb4",
    "cursorclass": DictCursor,
    # Con DB_SSL_CA la conexion va cifrada y se verifica el certificado del
    # servidor. En Azure es obligatorio; en desarrollo queda sin definir.
    "ssl_ca": os.getenv("DB_SSL_CA") or None,
}

# Solo para emparejar los examenes y medicamentos sembrados con su precio.
MS_COBROS_URL = os.getenv("MS_COBROS_URL", "http://ms-cobros:8082")


def get_conn() -> pymysql.connections.Connection:
    return pymysql.connect(**CONFIG)


class NombreRepetido(Exception):
    """Ya existe un registro con ese nombre (o ese numero de colegiado)."""


# ---------------------------------------------------------------------
# Esquema
#
# La especialidad es una tabla y no un texto: asi la regla RN-05 compara
# identificadores y no letras, y «Medicina  Interna» con dos espacios no
# puede existir. Nada se borra; lo que deja de usarse se desactiva, para
# que las visitas viejas sigan apuntando a algo.
# ---------------------------------------------------------------------

TABLAS = [
    """
    CREATE TABLE IF NOT EXISTS especialidades (
        id      INT AUTO_INCREMENT PRIMARY KEY,
        nombre  VARCHAR(60) NOT NULL UNIQUE,
        activo  BOOLEAN     NOT NULL DEFAULT TRUE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS medicos (
        id              INT AUTO_INCREMENT PRIMARY KEY,
        nombre          VARCHAR(120) NOT NULL,
        colegiado       VARCHAR(20)  NULL UNIQUE,
        especialidad_id INT          NOT NULL,
        activo          BOOLEAN      NOT NULL DEFAULT TRUE,
        INDEX idx_especialidad (especialidad_id),
        CONSTRAINT fk_medico_especialidad FOREIGN KEY (especialidad_id)
            REFERENCES especialidades (id) ON DELETE RESTRICT
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS enfermeros (
        id      INT AUTO_INCREMENT PRIMARY KEY,
        nombre  VARCHAR(120) NOT NULL,
        activo  BOOLEAN      NOT NULL DEFAULT TRUE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    # tarifa_id apunta a asilo_cobros.tarifas: es una relacion logica, sin
    # llave foranea, porque vive en el esquema de otro servicio.
    """
    CREATE TABLE IF NOT EXISTS tipos_examen (
        id         INT AUTO_INCREMENT PRIMARY KEY,
        nombre     VARCHAR(120) NOT NULL UNIQUE,
        tarifa_id  INT          NULL,
        activo     BOOLEAN      NOT NULL DEFAULT TRUE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS medicamentos (
        id            INT AUTO_INCREMENT PRIMARY KEY,
        nombre        VARCHAR(120) NOT NULL,
        presentacion  VARCHAR(80)  NULL,
        tarifa_id     INT          NULL,
        activo        BOOLEAN      NOT NULL DEFAULT TRUE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
]

# Como se lee cada recurso y que campos acepta al crear o modificar.
RECURSOS = {
    "especialidades": {
        "tabla": "especialidades",
        "select": "SELECT x.* FROM especialidades x",
        "campos": ("nombre", "activo"),
    },
    "medicos": {
        "tabla": "medicos",
        "select": (
            "SELECT x.*, e.nombre AS especialidad FROM medicos x "
            "JOIN especialidades e ON e.id = x.especialidad_id"
        ),
        "campos": ("nombre", "colegiado", "especialidad_id", "activo"),
    },
    "enfermeros": {
        "tabla": "enfermeros",
        "select": "SELECT x.* FROM enfermeros x",
        "campos": ("nombre", "activo"),
    },
    "examenes": {
        "tabla": "tipos_examen",
        "select": "SELECT x.* FROM tipos_examen x",
        "campos": ("nombre", "tarifa_id", "activo"),
    },
    "medicamentos": {
        "tabla": "medicamentos",
        "select": "SELECT x.* FROM medicamentos x",
        "campos": ("nombre", "presentacion", "tarifa_id", "activo"),
    },
}

# ---------------------------------------------------------------------
# Datos iniciales, para demostrar el sistema sin cargarlos a mano. Son
# nombres que se ven en pantalla, por eso llevan tildes.
# ---------------------------------------------------------------------

MEDICOS_SEMILLA = [
    ("Cardiología", "Dra. Ana Sical", "COL-10231"),
    ("Dermatología", "Dr. Mario Estrada", "COL-10412"),
    ("Endocrinología", "Dra. Lucía Barrios", "COL-10533"),
    ("Geriatría", "Dr. Fernando Ixcot", "COL-10654"),
    ("Medicina Interna", "Dra. Carmen Rodas", "COL-10775"),
    ("Nefrología", "Dr. Julio Pineda", "COL-10896"),
    ("Neumología", "Dra. Patricia Ajú", "COL-10917"),
    ("Neurología", "Dr. Ricardo Morales", "COL-11038"),
    ("Oftalmología", "Dra. Elena Chávez", "COL-11159"),
    ("Psiquiatría", "Dr. Andrés Fuentes", "COL-11270"),
    ("Traumatología", "Dr. Héctor Gómez", "COL-11391"),
    ("Urología", "Dr. Samuel Cifuentes", "COL-11412"),
]

ENFERMEROS_SEMILLA = ["Enf. Rosa Tzul", "Enf. Pedro Quiej", "Enf. María Coy", "Enf. José Batz"]

# Los nombres coinciden con los conceptos del tarifario de ms-cobros: asi
# cada examen y medicamento queda con su precio desde el primer arranque.
EXAMENES_SEMILLA = ["Hematología completa", "Glucosa en ayunas", "Radiografía de tórax"]

MEDICAMENTOS_SEMILLA = [("Losartán 50 mg", "caja"), ("Acetaminofén 500 mg", "caja")]


def init_db(intentos: int = 15, espera: float = 3.0) -> None:
    """
    Crea las tablas, siembra el catalogo si esta vacio y le pone precio a
    lo que todavia no lo tenga. Reintenta porque MySQL tarda mas que este
    contenedor en aceptar conexiones.
    """
    ultimo_error = None
    for intento in range(1, intentos + 1):
        try:
            conn = get_conn()
            with conn:
                with conn.cursor() as cur:
                    for tabla in TABLAS:
                        cur.execute(tabla)
                    cur.execute("SELECT COUNT(*) AS n FROM especialidades")
                    if cur.fetchone()["n"] == 0:
                        _sembrar(cur)
                        print("[ms-catalogo] Catalogo de demostracion creado.", flush=True)
                conn.commit()
            print(f"[ms-catalogo] Conectado a MySQL en el intento {intento}.", flush=True)
            break
        except pymysql.err.OperationalError as error:
            ultimo_error = error
            print(f"[ms-catalogo] MySQL aun no responde ({intento}/{intentos}).", flush=True)
            time.sleep(espera)
    else:
        raise RuntimeError(f"No se pudo conectar a MySQL: {ultimo_error}")

    vincular_tarifas()


def _sembrar(cur) -> None:
    for especialidad, _, _ in MEDICOS_SEMILLA:
        cur.execute("INSERT INTO especialidades (nombre) VALUES (%s)", (especialidad,))
    for especialidad, nombre, colegiado in MEDICOS_SEMILLA:
        cur.execute(
            """INSERT INTO medicos (nombre, colegiado, especialidad_id)
               SELECT %s, %s, id FROM especialidades WHERE nombre = %s""",
            (nombre, colegiado, especialidad),
        )
    cur.executemany("INSERT INTO enfermeros (nombre) VALUES (%s)", ENFERMEROS_SEMILLA)
    cur.executemany("INSERT INTO tipos_examen (nombre) VALUES (%s)", EXAMENES_SEMILLA)
    cur.executemany(
        "INSERT INTO medicamentos (nombre, presentacion) VALUES (%s, %s)", MEDICAMENTOS_SEMILLA
    )


def vincular_tarifas(intentos: int = 3, espera: float = 2.0) -> None:
    """
    Le pone precio a los examenes y medicamentos que no lo tienen, buscando
    en el tarifario un concepto con el mismo nombre.

    Si cobros no responde, se deja para el siguiente arranque: el precio
    tambien se puede elegir a mano en la pantalla del catalogo.
    """
    tarifas = None
    for _ in range(intentos):
        try:
            respuesta = httpx.get(f"{MS_COBROS_URL}/tarifas", timeout=3.0)
            respuesta.raise_for_status()
            tarifas = respuesta.json()
            break
        except httpx.HTTPError:
            time.sleep(espera)
    if tarifas is None:
        print("[ms-catalogo] Cobros no respondio; los precios quedan para despues.", flush=True)
        return

    por_nombre = {clave_de_comparacion(t["concepto"]): t["id"] for t in tarifas}
    conn = get_conn()
    with conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, nombre FROM tipos_examen WHERE tarifa_id IS NULL")
            for fila in cur.fetchall():
                tarifa_id = por_nombre.get(clave_de_comparacion(fila["nombre"]))
                if tarifa_id:
                    cur.execute(
                        "UPDATE tipos_examen SET tarifa_id = %s WHERE id = %s", (tarifa_id, fila["id"])
                    )
            cur.execute("SELECT id, nombre, presentacion FROM medicamentos WHERE tarifa_id IS NULL")
            for fila in cur.fetchall():
                nombre = f"{fila['nombre']} ({fila['presentacion']})" if fila["presentacion"] else fila["nombre"]
                tarifa_id = por_nombre.get(clave_de_comparacion(nombre))
                if tarifa_id:
                    cur.execute(
                        "UPDATE medicamentos SET tarifa_id = %s WHERE id = %s", (tarifa_id, fila["id"])
                    )
        conn.commit()


def _normalizar(fila: dict | None) -> dict | None:
    if fila is None:
        return None
    limpia = dict(fila)
    if "activo" in limpia:
        limpia["activo"] = bool(limpia["activo"])
    return limpia


# =====================================================================
# Metodos del repositorio, comunes a los cinco recursos
#
# El nombre de la tabla sale siempre de RECURSOS, nunca de la peticion:
# los valores van como parametros (%s), asi que no hay inyeccion SQL.
# =====================================================================

def contar(recurso: str) -> int:
    conn = get_conn()
    with conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) AS n FROM {RECURSOS[recurso]['tabla']} WHERE activo = TRUE")
            return cur.fetchone()["n"]


def listar(recurso: str, solo_activos: bool = False, especialidad_id: int | None = None) -> list[dict]:
    sql = RECURSOS[recurso]["select"] + " WHERE 1 = 1"
    params: list = []
    if solo_activos:
        sql += " AND x.activo = TRUE"
    if especialidad_id is not None and recurso == "medicos":
        sql += " AND x.especialidad_id = %s"
        params.append(especialidad_id)
    sql += " ORDER BY x.nombre"

    conn = get_conn()
    with conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return [_normalizar(f) for f in cur.fetchall()]


def obtener(recurso: str, registro_id: int) -> dict | None:
    conn = get_conn()
    with conn:
        with conn.cursor() as cur:
            cur.execute(RECURSOS[recurso]["select"] + " WHERE x.id = %s", (registro_id,))
            return _normalizar(cur.fetchone())


def crear(recurso: str, datos: dict) -> dict:
    """Lanza NombreRepetido si choca con un UNIQUE de la tabla."""
    definicion = RECURSOS[recurso]
    campos = [c for c in definicion["campos"] if c in datos]
    columnas = ", ".join(campos)
    marcadores = ", ".join(["%s"] * len(campos))

    conn = get_conn()
    with conn:
        with conn.cursor() as cur:
            try:
                cur.execute(
                    f"INSERT INTO {definicion['tabla']} ({columnas}) VALUES ({marcadores})",
                    [datos[c] for c in campos],
                )
            except pymysql.err.IntegrityError as error:
                if error.args[0] == 1062:
                    raise NombreRepetido() from error
                raise
            nuevo_id = cur.lastrowid
        conn.commit()
    return obtener(recurso, nuevo_id)


def actualizar(recurso: str, registro_id: int, cambios: dict) -> dict | None:
    """Devuelve None si no existe; lanza NombreRepetido si choca con un UNIQUE."""
    definicion = RECURSOS[recurso]
    permitidos = {k: v for k, v in cambios.items() if k in definicion["campos"]}
    asignaciones = ", ".join(f"{campo} = %s" for campo in permitidos)

    conn = get_conn()
    with conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT id FROM {definicion['tabla']} WHERE id = %s", (registro_id,))
            if cur.fetchone() is None:
                return None
            try:
                cur.execute(
                    f"UPDATE {definicion['tabla']} SET {asignaciones} WHERE id = %s",
                    [*permitidos.values(), registro_id],
                )
            except pymysql.err.IntegrityError as error:
                if error.args[0] == 1062:
                    raise NombreRepetido() from error
                raise
        conn.commit()
    return obtener(recurso, registro_id)
