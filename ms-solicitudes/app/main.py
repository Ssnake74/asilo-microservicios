"""
Microservicio de Solicitudes de Consulta y Visitas Medicas
Sistema para Administracion Asilo de Ancianos "Cabeza de Algodon"

Responsabilidad unica: registrar las solicitudes que genera el medico
general y convertirlas en visitas medicas formales, validando que exista
medico tratante y que la especialidad coincida con la remitida.

Al convertir una solicitud llama al microservicio de Cobros para generar
el cargo de la consulta.

Puerto: 8081
Documentacion interactiva: http://localhost:8081/docs
"""

from datetime import datetime

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from .cliente_cobros import generar_cargo_consulta
from .db import get_conn, init_db
from .schemas import (
    ConversionSolicitud,
    Solicitud,
    SolicitudCrear,
    Visita,
    VisitaCreada,
)

app = FastAPI(
    title="MS Solicitudes - Asilo Cabeza de Algodon",
    description=(
        "Microservicio de solicitudes de consulta y su conversion en visitas "
        "medicas formales."
    ),
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def al_iniciar() -> None:
    init_db()


def fila_a_solicitud(fila) -> dict:
    solicitud = dict(fila)
    solicitud["cubierto_fundacion"] = bool(solicitud["cubierto_fundacion"])
    return solicitud


def fila_a_visita(fila) -> dict:
    visita = dict(fila)
    visita["cargo_generado"] = bool(visita["cargo_generado"])
    return visita


# ---------------------------------------------------------------- salud


@app.get("/health", tags=["Estado"])
def health() -> dict:
    conn = get_conn()
    pendientes = conn.execute(
        "SELECT COUNT(*) AS n FROM solicitudes WHERE estado = 'PENDIENTE'"
    ).fetchone()["n"]
    conn.close()
    return {
        "servicio": "ms-solicitudes",
        "estado": "arriba",
        "solicitudes_pendientes": pendientes,
    }


# ------------------------------------------------------------ CRUD solicitudes


@app.post("/solicitudes", response_model=Solicitud, status_code=201, tags=["Solicitudes"])
def crear_solicitud(datos: SolicitudCrear):
    """Registra la solicitud de consulta que genera el medico general."""
    conn = get_conn()
    with conn:
        cursor = conn.execute(
            """INSERT INTO solicitudes (
                   paciente_id, paciente_nombre, familiar_email, medico_general,
                   especialidad_remitida, motivo, cubierto_fundacion, estado, fecha_solicitud)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'PENDIENTE', ?)""",
            (
                datos.paciente_id,
                datos.paciente_nombre,
                datos.familiar_email,
                datos.medico_general,
                datos.especialidad_remitida.strip().title(),
                datos.motivo,
                int(datos.cubierto_fundacion),
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        fila = conn.execute(
            "SELECT * FROM solicitudes WHERE id = ?", (cursor.lastrowid,)
        ).fetchone()
    conn.close()
    return fila_a_solicitud(fila)


@app.get("/solicitudes", response_model=list[Solicitud], tags=["Solicitudes"])
def listar_solicitudes(
    estado: str | None = Query(default=None, description="PENDIENTE, CONVERTIDA o ANULADA"),
    paciente_id: str | None = None,
):
    sql = "SELECT * FROM solicitudes WHERE 1 = 1"
    params: list = []
    if estado:
        sql += " AND estado = ?"
        params.append(estado.upper())
    if paciente_id:
        sql += " AND paciente_id = ?"
        params.append(paciente_id)
    sql += " ORDER BY id DESC"

    conn = get_conn()
    filas = conn.execute(sql, params).fetchall()
    conn.close()
    return [fila_a_solicitud(f) for f in filas]


@app.get("/solicitudes/{solicitud_id}", response_model=Solicitud, tags=["Solicitudes"])
def obtener_solicitud(solicitud_id: int):
    conn = get_conn()
    fila = conn.execute(
        "SELECT * FROM solicitudes WHERE id = ?", (solicitud_id,)
    ).fetchone()
    conn.close()
    if fila is None:
        raise HTTPException(status_code=404, detail="La solicitud no existe.")
    return fila_a_solicitud(fila)


@app.delete("/solicitudes/{solicitud_id}", status_code=204, tags=["Solicitudes"])
def anular_solicitud(solicitud_id: int):
    """Anula una solicitud pendiente. Las ya convertidas no se pueden anular."""
    conn = get_conn()
    fila = conn.execute(
        "SELECT * FROM solicitudes WHERE id = ?", (solicitud_id,)
    ).fetchone()
    if fila is None:
        conn.close()
        raise HTTPException(status_code=404, detail="La solicitud no existe.")
    if fila["estado"] == "CONVERTIDA":
        conn.close()
        raise HTTPException(
            status_code=409,
            detail="La solicitud ya tiene una visita medica asignada y no puede anularse.",
        )
    with conn:
        conn.execute(
            "UPDATE solicitudes SET estado = 'ANULADA' WHERE id = ?", (solicitud_id,)
        )
    conn.close()


# -------------------------------------------------- regla de negocio principal


@app.post(
    "/solicitudes/{solicitud_id}/convertir",
    response_model=VisitaCreada,
    status_code=201,
    tags=["Visitas"],
)
def convertir_en_visita(solicitud_id: int, datos: ConversionSolicitud):
    """
    Convierte una solicitud de consulta en una visita medica formal.

    Validaciones del negocio (documento de Estructura de Capas):
      1. La solicitud debe existir.
      2. Solo se convierten solicitudes en estado PENDIENTE.
      3. La visita debe tener medico tratante asignado.
      4. La especialidad del medico tratante debe coincidir con la
         especialidad remitida por el medico general.

    Si todo es valido, se crea la visita, la solicitud pasa a CONVERTIDA y
    se pide al microservicio de Cobros el cargo de la consulta.
    """
    conn = get_conn()
    solicitud = conn.execute(
        "SELECT * FROM solicitudes WHERE id = ?", (solicitud_id,)
    ).fetchone()

    if solicitud is None:
        conn.close()
        raise HTTPException(status_code=404, detail="La solicitud no existe.")

    if solicitud["estado"] != "PENDIENTE":
        conn.close()
        raise HTTPException(
            status_code=409,
            detail=f"La solicitud esta en estado {solicitud['estado']} y ya no puede convertirse.",
        )

    if not datos.medico_tratante.strip():
        conn.close()
        raise HTTPException(
            status_code=422, detail="La visita medica requiere un medico tratante."
        )

    especialidad = datos.especialidad.strip().title()
    if especialidad != solicitud["especialidad_remitida"]:
        conn.close()
        raise HTTPException(
            status_code=422,
            detail=(
                f"El medico general remitio a {solicitud['especialidad_remitida']}, "
                f"pero se intento asignar {especialidad}."
            ),
        )

    with conn:
        cursor = conn.execute(
            """INSERT INTO visitas (
                   solicitud_id, paciente_id, paciente_nombre, medico_tratante,
                   especialidad, fecha_visita, observaciones, cargo_generado)
               VALUES (?, ?, ?, ?, ?, ?, ?, 0)""",
            (
                solicitud_id,
                solicitud["paciente_id"],
                solicitud["paciente_nombre"],
                datos.medico_tratante.strip(),
                especialidad,
                datos.fecha_visita,
                datos.observaciones,
            ),
        )
        visita_id = cursor.lastrowid
        conn.execute(
            "UPDATE solicitudes SET estado = 'CONVERTIDA' WHERE id = ?", (solicitud_id,)
        )

    # Llamada al otro microservicio para generar el cobro de la consulta.
    cargo_id, mensaje_cobro = generar_cargo_consulta(
        paciente_id=solicitud["paciente_id"],
        paciente_nombre=solicitud["paciente_nombre"],
        familiar_email=solicitud["familiar_email"],
        cubierto_fundacion=bool(solicitud["cubierto_fundacion"]),
        referencia=f"VISITA-{visita_id}",
    )

    with conn:
        conn.execute(
            "UPDATE visitas SET cargo_id = ?, cargo_generado = ? WHERE id = ?",
            (cargo_id, int(cargo_id is not None), visita_id),
        )
        visita = conn.execute("SELECT * FROM visitas WHERE id = ?", (visita_id,)).fetchone()
        solicitud = conn.execute(
            "SELECT * FROM solicitudes WHERE id = ?", (solicitud_id,)
        ).fetchone()
    conn.close()

    return {
        "visita": fila_a_visita(visita),
        "solicitud": fila_a_solicitud(solicitud),
        "mensaje_cobro": mensaje_cobro,
    }


# ---------------------------------------------------------------- visitas


@app.get("/visitas", response_model=list[Visita], tags=["Visitas"])
def listar_visitas(paciente_id: str | None = None):
    sql = "SELECT * FROM visitas WHERE 1 = 1"
    params: list = []
    if paciente_id:
        sql += " AND paciente_id = ?"
        params.append(paciente_id)
    sql += " ORDER BY id DESC"

    conn = get_conn()
    filas = conn.execute(sql, params).fetchall()
    conn.close()
    return [fila_a_visita(f) for f in filas]


@app.get("/visitas/{visita_id}", response_model=Visita, tags=["Visitas"])
def obtener_visita(visita_id: int):
    conn = get_conn()
    fila = conn.execute("SELECT * FROM visitas WHERE id = ?", (visita_id,)).fetchone()
    conn.close()
    if fila is None:
        raise HTTPException(status_code=404, detail="La visita no existe.")
    return fila_a_visita(fila)
