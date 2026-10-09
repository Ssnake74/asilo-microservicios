"""
Microservicio de Solicitudes de Consulta y Visitas Medicas
Sistema para Administracion Asilo de Ancianos "Cabeza de Algodon"

Responsabilidad unica: registrar las solicitudes que genera el medico
general y convertirlas en visitas medicas formales, validando que exista
medico tratante y que la especialidad coincida con la remitida.

Al convertir una solicitud llama al microservicio de Cobros para generar
el cargo de la consulta.

Este archivo es la capa de presentacion/controlador del servicio: recibe
peticiones HTTP, aplica las reglas del negocio y responde. Desde la
migracion a MySQL ya no contiene una sola linea de SQL; todo el acceso a
datos pasa por db.py.

Puerto: 8081
Documentacion interactiva: http://localhost:8081/docs
"""

from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from . import db
from .cliente_cobros import generar_cargo_consulta
from .notificaciones import avisar_al_familiar
from .reglas import (
    especialidades_coinciden,
    normalizar_especialidad,
    normalizar_fecha_visita,
)
from .schemas import (
    ConversionSolicitud,
    Solicitud,
    SolicitudCrear,
    Visita,
    VisitaCreada,
)


@asynccontextmanager
async def ciclo_de_vida(app: FastAPI):
    """
    Prepara la base al arrancar el servicio.

    Reemplaza al @app.on_event("startup") de la version anterior, que
    FastAPI marco como obsoleto. Lo que va antes del 'yield' corre al
    encender el servicio; lo que fuera despues correria al apagarlo.
    """
    db.init_db()
    yield


app = FastAPI(
    title="MS Solicitudes - Asilo Cabeza de Algodon",
    description=(
        "Microservicio de solicitudes de consulta y su conversion en visitas "
        "medicas formales."
    ),
    version="2.0.0",
    lifespan=ciclo_de_vida,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------- salud


@app.get("/health", tags=["Estado"])
def health() -> dict:
    return {
        "servicio": "ms-solicitudes",
        "estado": "arriba",
        "motor": "MySQL",
        "solicitudes_pendientes": db.contar_pendientes(),
    }


# ------------------------------------------------------------ CRUD solicitudes


@app.post("/solicitudes", response_model=Solicitud, status_code=201, tags=["Solicitudes"])
def crear_solicitud(datos: SolicitudCrear, tareas: BackgroundTasks):
    """
    Registra la solicitud de consulta que genera el medico general y le
    avisa por correo al familiar del interno (RF-44).

    El aviso se encola como tarea de fondo: FastAPI lo ejecuta DESPUES de
    haber respondido. El medico ve su confirmacion de inmediato aunque el
    servidor de correo este lento o apagado.
    """
    valores = datos.model_dump()
    valores["especialidad_remitida"] = normalizar_especialidad(valores["especialidad_remitida"])
    solicitud = db.crear_solicitud(valores)

    tareas.add_task(avisar_al_familiar, solicitud)
    return solicitud


@app.get("/solicitudes", response_model=list[Solicitud], tags=["Solicitudes"])
def listar_solicitudes(
    estado: str | None = Query(default=None, description="PENDIENTE, CONVERTIDA o ANULADA"),
    paciente_id: str | None = None,
):
    return db.listar_solicitudes(estado=estado, paciente_id=paciente_id)


@app.get("/solicitudes/{solicitud_id}", response_model=Solicitud, tags=["Solicitudes"])
def obtener_solicitud(solicitud_id: int):
    solicitud = db.obtener_solicitud(solicitud_id)
    if solicitud is None:
        raise HTTPException(status_code=404, detail="La solicitud no existe.")
    return solicitud


@app.delete("/solicitudes/{solicitud_id}", status_code=204, tags=["Solicitudes"])
def anular_solicitud(solicitud_id: int):
    """Anula una solicitud pendiente. Las ya convertidas no se pueden anular."""
    solicitud = db.obtener_solicitud(solicitud_id)
    if solicitud is None:
        raise HTTPException(status_code=404, detail="La solicitud no existe.")
    if solicitud["estado"] == "CONVERTIDA":
        raise HTTPException(
            status_code=409,
            detail="La solicitud ya tiene una visita medica asignada y no puede anularse.",
        )
    if not db.anular_solicitud(solicitud_id):
        raise HTTPException(
            status_code=409,
            detail=f"La solicitud esta en estado {solicitud['estado']} y ya no puede anularse.",
        )


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
      5. La fecha de la visita debe ser una fecha valida (regla nueva:
         la columna ahora es DATETIME y no texto).

    Si todo es valido, se crea la visita, la solicitud pasa a CONVERTIDA
    y se le pide al microservicio de Cobros el cargo de la consulta.
    """
    solicitud = db.obtener_solicitud(solicitud_id)

    if solicitud is None:
        raise HTTPException(status_code=404, detail="La solicitud no existe.")

    if solicitud["estado"] != "PENDIENTE":
        raise HTTPException(
            status_code=409,
            detail=f"La solicitud esta en estado {solicitud['estado']} y ya no puede convertirse.",
        )

    if not datos.medico_tratante.strip():
        raise HTTPException(
            status_code=422, detail="La visita medica requiere un medico tratante."
        )

    especialidad = normalizar_especialidad(datos.especialidad)
    if not especialidades_coinciden(solicitud["especialidad_remitida"], datos.especialidad):
        raise HTTPException(
            status_code=422,
            detail=(
                f"El medico general remitio a {solicitud['especialidad_remitida']}, "
                f"pero se intento asignar {especialidad}."
            ),
        )

    try:
        fecha_visita = normalizar_fecha_visita(datos.fecha_visita)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))

    visita = db.convertir_en_visita(
        solicitud,
        {
            "medico_tratante": datos.medico_tratante.strip(),
            "especialidad": especialidad,
            "fecha_visita": fecha_visita,
            "observaciones": datos.observaciones,
        },
    )

    # db devuelve None si entre la consulta de arriba y el UPDATE alguien
    # mas convirtio o anulo la misma solicitud.
    if visita is None:
        raise HTTPException(
            status_code=409,
            detail="La solicitud dejo de estar pendiente mientras se asignaba la visita.",
        )

    # Llamada al otro microservicio para generar el cobro de la consulta.
    # Va FUERA de la transaccion de MySQL a proposito: si Cobros no
    # responde, la visita ya quedo guardada y el servicio no se cae.
    cargo_id, mensaje_cobro = generar_cargo_consulta(
        paciente_id=solicitud["paciente_id"],
        paciente_nombre=solicitud["paciente_nombre"],
        familiar_email=solicitud["familiar_email"],
        cubierto_fundacion=solicitud["cubierto_fundacion"],
        referencia=f"VISITA-{visita['id']}",
    )

    visita = db.registrar_cargo_en_visita(visita["id"], cargo_id)

    return {
        "visita": visita,
        "solicitud": db.obtener_solicitud(solicitud_id),
        "mensaje_cobro": mensaje_cobro,
    }


# ---------------------------------------------------------------- visitas


@app.get("/visitas", response_model=list[Visita], tags=["Visitas"])
def listar_visitas(paciente_id: str | None = None):
    return db.listar_visitas(paciente_id=paciente_id)


@app.get("/visitas/{visita_id}", response_model=Visita, tags=["Visitas"])
def obtener_visita(visita_id: int):
    visita = db.obtener_visita(visita_id)
    if visita is None:
        raise HTTPException(status_code=404, detail="La visita no existe.")
    return visita
