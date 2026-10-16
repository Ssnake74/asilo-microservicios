"""
Microservicio de Catalogo Medico
Sistema para Administracion Asilo de Ancianos "Cabeza de Algodon"

Especialidades, medicos, enfermeros, examenes de laboratorio y
medicamentos con que trabaja la fundacion. Los demas servicios los
consultan para no escribir esos nombres a mano. Capa de presentacion: el
SQL vive en db.py.

Todas las rutas van bajo /catalogo: el gateway reenvia ahi todo lo que
llega a /api/catalogo.

Puerto: 8084
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query

from . import db
from .reglas import limpiar_nombre
from .schemas import (
    Enfermero,
    EnfermeroActualizar,
    EnfermeroCrear,
    Especialidad,
    EspecialidadActualizar,
    EspecialidadCrear,
    Examen,
    ExamenActualizar,
    ExamenCrear,
    Medicamento,
    MedicamentoActualizar,
    MedicamentoCrear,
    Medico,
    MedicoActualizar,
    MedicoCrear,
)


@asynccontextmanager
async def ciclo_de_vida(app: FastAPI):
    """Prepara la base al arrancar el servicio."""
    db.init_db()
    yield


app = FastAPI(
    title="MS Catalogo - Asilo Cabeza de Algodon",
    description="Catalogo medico: especialidades, medicos, enfermeros, examenes y medicamentos.",
    version="1.0.0",
    lifespan=ciclo_de_vida,
)

# Como se nombra cada recurso en los mensajes que llegan a la pantalla.
NOMBRE = {
    "especialidades": ("La especialidad", "una especialidad"),
    "medicos": ("El médico", "un médico"),
    "enfermeros": ("El enfermero", "un enfermero"),
    "examenes": ("El examen", "un examen"),
    "medicamentos": ("El medicamento", "un medicamento"),
}


# ------------------------------------------------- operaciones comunes

def _obtener(recurso: str, registro_id: int) -> dict:
    registro = db.obtener(recurso, registro_id)
    if registro is None:
        raise HTTPException(status_code=404, detail=f"{NOMBRE[recurso][0]} no existe.")
    return registro


def _limpiar(datos: dict) -> dict:
    """Nombres con un solo espacio entre palabras; textos vacios pasan a None."""
    limpios = dict(datos)
    for campo in ("nombre", "colegiado", "presentacion"):
        if isinstance(limpios.get(campo), str):
            limpios[campo] = limpiar_nombre(limpios[campo]) or None
    if "nombre" in limpios and limpios["nombre"] is None:
        raise HTTPException(status_code=422, detail="El nombre no puede quedar en blanco.")
    return limpios


def _exigir_especialidad(especialidad_id: int) -> None:
    especialidad = db.obtener("especialidades", especialidad_id)
    if especialidad is None or not especialidad["activo"]:
        raise HTTPException(
            status_code=422,
            detail="La especialidad indicada no existe o ya no está en uso.",
        )


def _crear(recurso: str, datos: dict) -> dict:
    try:
        return db.crear(recurso, _limpiar(datos))
    except db.NombreRepetido:
        raise HTTPException(
            status_code=409,
            detail=f"Ya existe {NOMBRE[recurso][1]} con ese nombre o ese número.",
        )


def _actualizar(recurso: str, registro_id: int, datos) -> dict:
    cambios = _limpiar(datos.model_dump(exclude_unset=True))
    if not cambios:
        raise HTTPException(status_code=400, detail="No se enviaron campos por actualizar.")
    try:
        registro = db.actualizar(recurso, registro_id, cambios)
    except db.NombreRepetido:
        raise HTTPException(
            status_code=409,
            detail=f"Ya existe {NOMBRE[recurso][1]} con ese nombre o ese número.",
        )
    if registro is None:
        raise HTTPException(status_code=404, detail=f"{NOMBRE[recurso][0]} no existe.")
    return registro


# ---------------------------------------------------------------- salud

@app.get("/health", tags=["Estado"])
def health() -> dict:
    return {
        "servicio": "ms-catalogo",
        "estado": "arriba",
        "motor": "MySQL",
        "medicos_activos": db.contar("medicos"),
    }


# ------------------------------------------------------- especialidades

@app.get("/catalogo/especialidades", response_model=list[Especialidad], tags=["Especialidades"])
def listar_especialidades(solo_activas: bool = False):
    return db.listar("especialidades", solo_activos=solo_activas)


@app.get("/catalogo/especialidades/{registro_id}", response_model=Especialidad, tags=["Especialidades"])
def obtener_especialidad(registro_id: int):
    return _obtener("especialidades", registro_id)


@app.post("/catalogo/especialidades", response_model=Especialidad, status_code=201, tags=["Especialidades"])
def crear_especialidad(datos: EspecialidadCrear):
    return _crear("especialidades", datos.model_dump())


@app.put("/catalogo/especialidades/{registro_id}", response_model=Especialidad, tags=["Especialidades"])
def actualizar_especialidad(registro_id: int, datos: EspecialidadActualizar):
    return _actualizar("especialidades", registro_id, datos)


# --------------------------------------------------------------- medicos

@app.get("/catalogo/medicos", response_model=list[Medico], tags=["Médicos"])
def listar_medicos(
    solo_activos: bool = False,
    especialidad_id: int | None = Query(default=None, description="Solo los de esa especialidad"),
):
    return db.listar("medicos", solo_activos=solo_activos, especialidad_id=especialidad_id)


@app.get("/catalogo/medicos/{registro_id}", response_model=Medico, tags=["Médicos"])
def obtener_medico(registro_id: int):
    return _obtener("medicos", registro_id)


@app.post("/catalogo/medicos", response_model=Medico, status_code=201, tags=["Médicos"])
def crear_medico(datos: MedicoCrear):
    _exigir_especialidad(datos.especialidad_id)
    return _crear("medicos", datos.model_dump())


@app.put("/catalogo/medicos/{registro_id}", response_model=Medico, tags=["Médicos"])
def actualizar_medico(registro_id: int, datos: MedicoActualizar):
    if datos.especialidad_id is not None:
        _exigir_especialidad(datos.especialidad_id)
    return _actualizar("medicos", registro_id, datos)


# ------------------------------------------------------------ enfermeros

@app.get("/catalogo/enfermeros", response_model=list[Enfermero], tags=["Enfermeros"])
def listar_enfermeros(solo_activos: bool = False):
    return db.listar("enfermeros", solo_activos=solo_activos)


@app.get("/catalogo/enfermeros/{registro_id}", response_model=Enfermero, tags=["Enfermeros"])
def obtener_enfermero(registro_id: int):
    return _obtener("enfermeros", registro_id)


@app.post("/catalogo/enfermeros", response_model=Enfermero, status_code=201, tags=["Enfermeros"])
def crear_enfermero(datos: EnfermeroCrear):
    return _crear("enfermeros", datos.model_dump())


@app.put("/catalogo/enfermeros/{registro_id}", response_model=Enfermero, tags=["Enfermeros"])
def actualizar_enfermero(registro_id: int, datos: EnfermeroActualizar):
    return _actualizar("enfermeros", registro_id, datos)


# -------------------------------------------------------------- examenes

@app.get("/catalogo/examenes", response_model=list[Examen], tags=["Exámenes"])
def listar_examenes(solo_activos: bool = False):
    return db.listar("examenes", solo_activos=solo_activos)


@app.get("/catalogo/examenes/{registro_id}", response_model=Examen, tags=["Exámenes"])
def obtener_examen(registro_id: int):
    return _obtener("examenes", registro_id)


@app.post("/catalogo/examenes", response_model=Examen, status_code=201, tags=["Exámenes"])
def crear_examen(datos: ExamenCrear):
    return _crear("examenes", datos.model_dump())


@app.put("/catalogo/examenes/{registro_id}", response_model=Examen, tags=["Exámenes"])
def actualizar_examen(registro_id: int, datos: ExamenActualizar):
    return _actualizar("examenes", registro_id, datos)


# ---------------------------------------------------------- medicamentos

@app.get("/catalogo/medicamentos", response_model=list[Medicamento], tags=["Medicamentos"])
def listar_medicamentos(solo_activos: bool = False):
    return db.listar("medicamentos", solo_activos=solo_activos)


@app.get("/catalogo/medicamentos/{registro_id}", response_model=Medicamento, tags=["Medicamentos"])
def obtener_medicamento(registro_id: int):
    return _obtener("medicamentos", registro_id)


@app.post("/catalogo/medicamentos", response_model=Medicamento, status_code=201, tags=["Medicamentos"])
def crear_medicamento(datos: MedicamentoCrear):
    return _crear("medicamentos", datos.model_dump())


@app.put("/catalogo/medicamentos/{registro_id}", response_model=Medicamento, tags=["Medicamentos"])
def actualizar_medicamento(registro_id: int, datos: MedicamentoActualizar):
    return _actualizar("medicamentos", registro_id, datos)
