"""
Capa de Acceso a Datos del microservicio Clinico (esquema asilo_clinico).

Es el unico archivo del servicio con SQL. Las cinco tablas son las de la
seccion 17.2 del ERS: la ficha medica de la visita, las ordenes de
examen con su resultado y las recetas con su despacho.

La ficha copia del resto del sistema lo que necesita para mostrarse y
para cobrar (interno, especialidad, medico, si lo cubre la fundacion):
la visita vive en otro esquema y no se puede hacer JOIN contra ella.
"""

import os
import time
from datetime import date, datetime

import pymysql
from pymysql.cursors import DictCursor

from .reglas import COMPLETADA, DESPACHADA, PENDIENTE

CONFIG = {
    "host": os.getenv("DB_HOST", "mysql"),
    "port": int(os.getenv("DB_PORT", "3306")),
    "user": os.getenv("DB_USER", "u_clinico"),
    "password": os.getenv("DB_PASSWORD", "clinico_2026"),
    "database": os.getenv("DB_NAME", "asilo_clinico"),
    "charset": "utf8mb4",
    "cursorclass": DictCursor,
    # Con DB_SSL_CA la conexion va cifrada y se verifica el certificado del
    # servidor. En Azure es obligatorio; en desarrollo queda sin definir.
    "ssl_ca": os.getenv("DB_SSL_CA") or None,
}


def get_conn() -> pymysql.connections.Connection:
    return pymysql.connect(**CONFIG)


class YaExiste(Exception):
    """La visita ya tiene ficha, o la orden ya tiene resultado, o la receta ya se despacho."""


# ---------------------------------------------------------------------
# Esquema
#
# visita_id, tipo_examen_id y medicamento_id apuntan a otros esquemas:
# relacion logica, sin llave foranea. Dentro de este esquema si hay
# llaves foraneas, y los UNIQUE impiden dos fichas para una visita, dos
# resultados para una orden y dos despachos para una receta.
# ---------------------------------------------------------------------

TABLAS = [
    """
    CREATE TABLE IF NOT EXISTS fichas_medicas (
        id                  INT AUTO_INCREMENT PRIMARY KEY,
        visita_id           INT           NOT NULL UNIQUE,
        paciente_id         VARCHAR(40)   NOT NULL,
        paciente_nombre     VARCHAR(120)  NOT NULL,
        familiar_email      VARCHAR(120)  NULL,
        cubierto_fundacion  BOOLEAN       NOT NULL DEFAULT FALSE,
        especialidad        VARCHAR(60)   NOT NULL,
        medico              VARCHAR(120)  NOT NULL,
        fecha_visita        DATETIME      NOT NULL,
        diagnostico         VARCHAR(1000) NOT NULL,
        observaciones       VARCHAR(1000) NULL,
        fecha               DATETIME      NOT NULL,
        responsable         VARCHAR(120)  NULL,
        INDEX idx_paciente (paciente_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS ordenes_examen (
        id              INT AUTO_INCREMENT PRIMARY KEY,
        ficha_id        INT          NOT NULL,
        tipo_examen_id  INT          NOT NULL,
        examen          VARCHAR(120) NOT NULL,
        tarifa_id       INT          NULL,
        indicaciones    VARCHAR(300) NULL,
        estado          VARCHAR(12)  NOT NULL DEFAULT 'PENDIENTE',
        fecha_orden     DATETIME     NOT NULL,
        cargo_id        INT          NULL,
        cargo_generado  BOOLEAN      NOT NULL DEFAULT FALSE,
        INDEX idx_estado (estado),
        CONSTRAINT fk_orden_ficha FOREIGN KEY (ficha_id) REFERENCES fichas_medicas (id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS resultados (
        id               INT AUTO_INCREMENT PRIMARY KEY,
        orden_id         INT           NOT NULL UNIQUE,
        resultado        VARCHAR(2000) NOT NULL,
        fecha_resultado  DATETIME      NOT NULL,
        responsable      VARCHAR(120)  NULL,
        CONSTRAINT fk_resultado_orden FOREIGN KEY (orden_id) REFERENCES ordenes_examen (id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS recetas (
        id              INT AUTO_INCREMENT PRIMARY KEY,
        ficha_id        INT          NOT NULL,
        medicamento_id  INT          NOT NULL,
        medicamento     VARCHAR(160) NOT NULL,
        tarifa_id       INT          NULL,
        cantidad        INT          NOT NULL,
        indicaciones    VARCHAR(300) NOT NULL,
        estado          VARCHAR(12)  NOT NULL DEFAULT 'PENDIENTE',
        fecha           DATETIME     NOT NULL,
        INDEX idx_estado (estado),
        CONSTRAINT fk_receta_ficha FOREIGN KEY (ficha_id) REFERENCES fichas_medicas (id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS despachos (
        id                   INT AUTO_INCREMENT PRIMARY KEY,
        receta_id            INT          NOT NULL UNIQUE,
        cantidad_despachada  INT          NOT NULL,
        fecha                DATETIME     NOT NULL,
        responsable          VARCHAR(120) NULL,
        cargo_id             INT          NULL,
        cargo_generado       BOOLEAN      NOT NULL DEFAULT FALSE,
        CONSTRAINT fk_despacho_receta FOREIGN KEY (receta_id) REFERENCES recetas (id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
]


def init_db(intentos: int = 15, espera: float = 3.0) -> None:
    """Crea las tablas. Reintenta porque MySQL tarda mas que este contenedor en arrancar."""
    ultimo_error = None
    for intento in range(1, intentos + 1):
        try:
            conn = get_conn()
            with conn:
                with conn.cursor() as cur:
                    for tabla in TABLAS:
                        cur.execute(tabla)
                conn.commit()
            print(f"[ms-clinico] Conectado a MySQL en el intento {intento}.", flush=True)
            return
        except pymysql.err.OperationalError as error:
            ultimo_error = error
            print(f"[ms-clinico] MySQL aun no responde ({intento}/{intentos}).", flush=True)
            time.sleep(espera)
    raise RuntimeError(f"No se pudo conectar a MySQL: {ultimo_error}")


def ahora() -> datetime:
    return datetime.now().replace(microsecond=0)


def _normalizar(fila: dict | None) -> dict | None:
    if fila is None:
        return None
    limpia = dict(fila)
    for campo, valor in limpia.items():
        if isinstance(valor, datetime):
            limpia[campo] = valor.isoformat(sep=" ", timespec="minutes")
        elif isinstance(valor, date):
            limpia[campo] = valor.isoformat()
    for campo in ("cubierto_fundacion", "cargo_generado"):
        if campo in limpia and limpia[campo] is not None:
            limpia[campo] = bool(limpia[campo])
    return limpia


def _insertar(cur, sql: str, valores: tuple) -> int:
    try:
        cur.execute(sql, valores)
    except pymysql.err.IntegrityError as error:
        if error.args and error.args[0] == 1062:
            raise YaExiste from error
        raise
    return cur.lastrowid


# Las columnas de la ficha que acompanan a cada orden y receta en las
# listas del laboratorio y la farmacia: para saber de quien es sin otra
# consulta.
DE_LA_FICHA = "f.visita_id, f.paciente_id, f.paciente_nombre, f.especialidad, f.medico"


# =====================================================================
# Fichas
# =====================================================================

def crear_ficha(visita: dict, diagnostico: str, observaciones: str | None,
                responsable: str | None) -> int:
    conn = get_conn()
    with conn:
        with conn.cursor() as cur:
            nuevo = _insertar(
                cur,
                """INSERT INTO fichas_medicas
                   (visita_id, paciente_id, paciente_nombre, familiar_email, cubierto_fundacion,
                    especialidad, medico, fecha_visita, diagnostico, observaciones, fecha, responsable)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    visita["id"], visita["paciente_id"], visita["paciente_nombre"],
                    visita.get("familiar_email"), bool(visita.get("cubierto_fundacion")),
                    visita["especialidad"], visita["medico_tratante"], visita["fecha_visita"],
                    diagnostico, observaciones, ahora(), responsable,
                ),
            )
        conn.commit()
    return nuevo


def obtener_ficha_simple(ficha_id: int) -> dict | None:
    """La fila de la ficha sola, con lo necesario para cobrar."""
    conn = get_conn()
    with conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM fichas_medicas WHERE id = %s", (ficha_id,))
            return _normalizar(cur.fetchone())


def listar_fichas(paciente_id: str | None = None, visita_id: int | None = None) -> list[dict]:
    """
    Fichas completas, de la mas reciente a la mas vieja, cada una con sus
    examenes y recetas. Es el historial medico del interno (RF-26).
    """
    sql = "SELECT * FROM fichas_medicas WHERE 1 = 1"
    params: list = []
    if paciente_id:
        sql += " AND paciente_id = %s"
        params.append(paciente_id)
    if visita_id is not None:
        sql += " AND visita_id = %s"
        params.append(visita_id)
    sql += " ORDER BY fecha_visita DESC, id DESC"

    conn = get_conn()
    with conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            fichas = [_normalizar(f) for f in cur.fetchall()]
    if not fichas:
        return []
    ids = [f["id"] for f in fichas]
    ordenes = listar_ordenes(fichas=ids)
    recetas = listar_recetas(fichas=ids)
    for ficha in fichas:
        ficha["examenes"] = [o for o in ordenes if o["ficha_id"] == ficha["id"]]
        ficha["recetas"] = [r for r in recetas if r["ficha_id"] == ficha["id"]]
    return fichas


def obtener_ficha(ficha_id: int) -> dict | None:
    conn = get_conn()
    with conn:
        with conn.cursor() as cur:
            cur.execute("SELECT visita_id FROM fichas_medicas WHERE id = %s", (ficha_id,))
            fila = cur.fetchone()
    if fila is None:
        return None
    return listar_fichas(visita_id=fila["visita_id"])[0]


# =====================================================================
# Ordenes de examen y resultados
# =====================================================================

def _filtro_ids(columna: str, ids: list[int]) -> tuple[str, list]:
    return f" AND {columna} IN ({', '.join(['%s'] * len(ids))})", list(ids)


def listar_ordenes(estado: str | None = None, paciente_id: str | None = None,
                   fichas: list[int] | None = None, orden_id: int | None = None) -> list[dict]:
    sql = f"""SELECT o.*, {DE_LA_FICHA},
                     r.resultado, r.fecha_resultado, r.responsable AS responsable_resultado
              FROM ordenes_examen o
              JOIN fichas_medicas f ON f.id = o.ficha_id
              LEFT JOIN resultados r ON r.orden_id = o.id
              WHERE 1 = 1"""
    params: list = []
    if estado:
        sql += " AND o.estado = %s"
        params.append(estado)
    if paciente_id:
        sql += " AND f.paciente_id = %s"
        params.append(paciente_id)
    if fichas is not None:
        if not fichas:
            return []
        extra, valores = _filtro_ids("o.ficha_id", fichas)
        sql += extra
        params += valores
    if orden_id is not None:
        sql += " AND o.id = %s"
        params.append(orden_id)
    sql += " ORDER BY o.fecha_orden, o.id"

    conn = get_conn()
    with conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            filas = [_normalizar(f) for f in cur.fetchall()]
    for fila in filas:
        resultado = fila.pop("resultado")
        fecha = fila.pop("fecha_resultado")
        responsable = fila.pop("responsable_resultado")
        fila["resultado"] = (
            {"resultado": resultado, "fecha_resultado": fecha, "responsable": responsable}
            if resultado is not None else None
        )
    return filas


def obtener_orden(orden_id: int) -> dict | None:
    filas = listar_ordenes(orden_id=orden_id)
    return filas[0] if filas else None


def crear_orden(ficha_id: int, examen: dict, indicaciones: str | None) -> int:
    conn = get_conn()
    with conn:
        with conn.cursor() as cur:
            nuevo = _insertar(
                cur,
                """INSERT INTO ordenes_examen
                   (ficha_id, tipo_examen_id, examen, tarifa_id, indicaciones, estado, fecha_orden)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                (ficha_id, examen["id"], examen["nombre"], examen.get("tarifa_id"),
                 indicaciones, PENDIENTE, ahora()),
            )
        conn.commit()
    return nuevo


def registrar_resultado(orden_id: int, resultado: str, responsable: str | None) -> bool:
    """
    Guarda el resultado y cierra la orden en una sola transaccion. Devuelve
    False si la orden ya no estaba pendiente: dos personas del laboratorio
    no pueden dejarle dos resultados.
    """
    conn = get_conn()
    with conn:
        with conn.cursor() as cur:
            cambiadas = cur.execute(
                "UPDATE ordenes_examen SET estado = %s WHERE id = %s AND estado = %s",
                (COMPLETADA, orden_id, PENDIENTE),
            )
            if cambiadas == 0:
                conn.rollback()
                return False
            _insertar(
                cur,
                """INSERT INTO resultados (orden_id, resultado, fecha_resultado, responsable)
                   VALUES (%s, %s, %s, %s)""",
                (orden_id, resultado, ahora(), responsable),
            )
        conn.commit()
    return True


def anotar_cargo_de_orden(orden_id: int, cargo_id: int | None) -> None:
    conn = get_conn()
    with conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE ordenes_examen SET cargo_id = %s, cargo_generado = %s WHERE id = %s",
                (cargo_id, cargo_id is not None, orden_id),
            )
        conn.commit()


# =====================================================================
# Recetas y despachos
# =====================================================================

def listar_recetas(estado: str | None = None, paciente_id: str | None = None,
                   fichas: list[int] | None = None, receta_id: int | None = None) -> list[dict]:
    sql = f"""SELECT re.*, {DE_LA_FICHA},
                     d.cantidad_despachada, d.fecha AS fecha_despacho,
                     d.responsable AS responsable_despacho,
                     d.cargo_id AS cargo_despacho, d.cargo_generado AS cargo_generado_despacho
              FROM recetas re
              JOIN fichas_medicas f ON f.id = re.ficha_id
              LEFT JOIN despachos d ON d.receta_id = re.id
              WHERE 1 = 1"""
    params: list = []
    if estado:
        sql += " AND re.estado = %s"
        params.append(estado)
    if paciente_id:
        sql += " AND f.paciente_id = %s"
        params.append(paciente_id)
    if fichas is not None:
        if not fichas:
            return []
        extra, valores = _filtro_ids("re.ficha_id", fichas)
        sql += extra
        params += valores
    if receta_id is not None:
        sql += " AND re.id = %s"
        params.append(receta_id)
    sql += " ORDER BY re.fecha, re.id"

    conn = get_conn()
    with conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            filas = [_normalizar(f) for f in cur.fetchall()]
    for fila in filas:
        cantidad = fila.pop("cantidad_despachada")
        despacho = {
            "cantidad_despachada": cantidad,
            "fecha": fila.pop("fecha_despacho"),
            "responsable": fila.pop("responsable_despacho"),
            "cargo_id": fila.pop("cargo_despacho"),
            "cargo_generado": bool(fila.pop("cargo_generado_despacho")),
        }
        fila["despacho"] = despacho if cantidad is not None else None
    return filas


def obtener_receta(receta_id: int) -> dict | None:
    filas = listar_recetas(receta_id=receta_id)
    return filas[0] if filas else None


def crear_receta(ficha_id: int, medicamento: dict, cantidad: int, indicaciones: str) -> int:
    nombre = medicamento["nombre"]
    if medicamento.get("presentacion"):
        nombre = f"{nombre} ({medicamento['presentacion']})"
    conn = get_conn()
    with conn:
        with conn.cursor() as cur:
            nuevo = _insertar(
                cur,
                """INSERT INTO recetas
                   (ficha_id, medicamento_id, medicamento, tarifa_id, cantidad, indicaciones, estado, fecha)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                (ficha_id, medicamento["id"], nombre[:160], medicamento.get("tarifa_id"),
                 cantidad, indicaciones, PENDIENTE, ahora()),
            )
        conn.commit()
    return nuevo


def registrar_despacho(receta_id: int, cantidad: int, responsable: str | None) -> int | None:
    """Guarda el despacho y cierra la receta; None si la receta ya no estaba pendiente."""
    conn = get_conn()
    with conn:
        with conn.cursor() as cur:
            cambiadas = cur.execute(
                "UPDATE recetas SET estado = %s WHERE id = %s AND estado = %s",
                (DESPACHADA, receta_id, PENDIENTE),
            )
            if cambiadas == 0:
                conn.rollback()
                return None
            nuevo = _insertar(
                cur,
                """INSERT INTO despachos (receta_id, cantidad_despachada, fecha, responsable)
                   VALUES (%s, %s, %s, %s)""",
                (receta_id, cantidad, ahora(), responsable),
            )
        conn.commit()
    return nuevo


def anotar_cargo_de_despacho(despacho_id: int, cargo_id: int | None) -> None:
    conn = get_conn()
    with conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE despachos SET cargo_id = %s, cargo_generado = %s WHERE id = %s",
                (cargo_id, cargo_id is not None, despacho_id),
            )
        conn.commit()


def contar_pendientes() -> dict:
    conn = get_conn()
    with conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM ordenes_examen WHERE estado = %s", (PENDIENTE,))
            examenes = cur.fetchone()["n"]
            cur.execute("SELECT COUNT(*) AS n FROM recetas WHERE estado = %s", (PENDIENTE,))
            recetas = cur.fetchone()["n"]
    return {"examenes_pendientes": examenes, "recetas_pendientes": recetas}
