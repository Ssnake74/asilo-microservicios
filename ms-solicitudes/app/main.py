"""
Microservicio de Solicitudes de Consulta y Visitas Medicas
Sistema para Administracion Asilo de Ancianos "Cabeza de Algodon"

Registra las solicitudes del medico general y las convierte en visitas
medicas, pidiendo a ms-cobros el cargo de la consulta. Especialidad,
medico y enfermero salen de ms-catalogo. Capa de presentacion: recibe
HTTP y aplica las reglas; el SQL vive en db.py.

Puerto: 8081
"""

from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query

from . import db
from .cliente_catalogo import (
    CatalogoNoDisponible,
    obtener_enfermero,
    obtener_especialidad,
    obtener_medico,
)
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
    """Prepara la base al arrancar el servicio."""
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


def _del_catalogo(consulta, registro_id: int) -> dict | None:
    """Consulta el catalogo; si no responde, la operacion se detiene con 503."""
    try:
        return consulta(registro_id)
    except CatalogoNoDisponible:
        raise HTTPException(
            status_code=503,
            detail="El catálogo médico no está disponible en este momento.",
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

    El aviso va como tarea de fondo y sale despues de responder: el
    medico ve su confirmacion aunque el servidor de correo este caido.
    """
    valores = datos.model_dump()
    if valores["especialidad_id"] is not None:
        especialidad = _del_catalogo(obtener_especialidad, valores["especialidad_id"])
        if especialidad is None or not especialidad["activo"]:
            raise HTTPException(
                status_code=422,
                detail="La especialidad elegida no existe en el catálogo o ya no está en uso.",
            )
        valores["especialidad_remitida"] = especialidad["nombre"]
    else:
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

    Validaciones del negocio:
      1. La solicitud debe existir.
      2. Solo se convierten solicitudes en estado PENDIENTE.
      3. La visita debe tener medico tratante asignado (RN-06).
      4. La especialidad del medico tratante debe coincidir con la
         especialidad remitida por el medico general (RN-05). Si ambos
         vienen del catalogo se comparan los identificadores.
      5. El enfermero acompanante, si se indica, debe estar en el
         catalogo (RF-20).
      6. La fecha de la visita debe ser una fecha valida.

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

    if datos.medico_id is not None:
        medico = _del_catalogo(obtener_medico, datos.medico_id)
        if medico is None or not medico["activo"]:
            raise HTTPException(
                status_code=422,
                detail="El médico elegido no existe en el catálogo o ya no atiende.",
            )
        if solicitud["especialidad_id"] is not None:
            misma = medico["especialidad_id"] == solicitud["especialidad_id"]
        else:
            misma = especialidades_coinciden(solicitud["especialidad_remitida"], medico["especialidad"])
        if not misma:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"El médico general remitió a {solicitud['especialidad_remitida']}, "
                    f"pero {medico['nombre']} es de {medico['especialidad']}."
                ),
            )
        medico_tratante, especialidad = medico["nombre"], medico["especialidad"]
    else:
        if not (datos.medico_tratante or "").strip():
            raise HTTPException(
                status_code=422, detail="La visita medica requiere un medico tratante."
            )
        if not datos.especialidad:
            raise HTTPException(
                status_code=422, detail="Indique la especialidad del medico tratante."
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
        medico_tratante = datos.medico_tratante.strip()

    enfermero = None
    if datos.enfermero_id is not None:
        enfermero = _del_catalogo(obtener_enfermero, datos.enfermero_id)
        if enfermero is None or not enfermero["activo"]:
            raise HTTPException(
                status_code=422,
                detail="El enfermero elegido no existe en el catálogo o ya no trabaja.",
            )

    try:
        fecha_visita = normalizar_fecha_visita(datos.fecha_visita)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))

    visita = db.convertir_en_visita(
        solicitud,
        {
            "medico_id": datos.medico_id,
            "medico_tratante": medico_tratante,
            "especialidad": especialidad,
            "enfermero_id": datos.enfermero_id,
            "enfermero": enfermero["nombre"] if enfermero else None,
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

    # Va fuera de la transaccion a proposito: si cobros no responde, la
    # visita ya quedo guardada (RNF-12).
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
