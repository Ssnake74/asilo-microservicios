"""
Microservicio de Registro de Ancianos (Pacientes internos)
Sistema para Administracion Asilo de Ancianos "Cabeza de Algodon"

Registro de los ancianos internos: datos personales, familiar responsable
y estado dentro del asilo. Capa de presentacion: recibe las peticiones
HTTP y aplica las reglas; el SQL vive en db.py.

Puerto: 8083
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query

from . import db
from .reglas import calcular_edad, fecha_de_egreso, ingreso_es_coherente
from .schemas import Paciente, PacienteActualizar, PacienteCrear


@asynccontextmanager
async def ciclo_de_vida(app: FastAPI):
    """Prepara la base al arrancar el servicio."""
    db.init_db()
    yield


app = FastAPI(
    title="MS Pacientes - Asilo Cabeza de Algodon",
    description="Microservicio de registro de los ancianos internos del asilo.",
    version="2.0.0",
    lifespan=ciclo_de_vida,
)


def con_edad(paciente: dict) -> dict:
    """Agrega la edad calculada, que no se guarda en la base."""
    paciente["edad"] = calcular_edad(paciente["fecha_nacimiento"])
    return paciente


def datos_de_egreso(actual: dict, cambios: dict) -> dict:
    """
    Al pasar a EGRESADO o FALLECIDO se anota cuando y por que; al volver a
    ACTIVO (un reingreso) se borran. La ficha y su historial no se tocan
    en ningun caso (RF-13).
    """
    if cambios["estado"] == "ACTIVO":
        return {"fecha_egreso": None, "motivo_egreso": None}
    try:
        fecha = fecha_de_egreso(cambios.get("fecha_egreso"), actual["fecha_ingreso"])
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    motivo = " ".join((cambios.get("motivo_egreso") or "").split()) or None
    return {"fecha_egreso": fecha, "motivo_egreso": motivo}


# ---------------------------------------------------------------- salud

@app.get("/health", tags=["Estado"])
def health() -> dict:
    return {
        "servicio": "ms-pacientes",
        "estado": "arriba",
        "motor": "MySQL",
        "ancianos_activos": db.contar_activos(),
    }


# ------------------------------------------------------------ pacientes

@app.post("/pacientes", response_model=Paciente, status_code=201, tags=["Pacientes"])
def registrar_paciente(datos: PacienteCrear):
    """Da de alta a un anciano en el asilo y le asigna su codigo correlativo."""
    if not ingreso_es_coherente(datos.fecha_nacimiento, datos.fecha_ingreso):
        raise HTTPException(
            status_code=422,
            detail="La fecha de ingreso no puede ser anterior a la fecha de nacimiento.",
        )

    if datos.dpi:
        repetido = db.dpi_ya_registrado(datos.dpi)
        if repetido:
            raise HTTPException(
                status_code=409,
                detail=f"Ese DPI ya está registrado con el código {repetido}.",
            )

    valores = datos.model_dump()
    valores["nombres"] = valores["nombres"].strip()
    valores["apellidos"] = valores["apellidos"].strip()
    valores["familiar_nombre"] = valores["familiar_nombre"].strip()

    return con_edad(db.crear(valores))


@app.get("/pacientes", response_model=list[Paciente], tags=["Pacientes"])
def listar_pacientes(
    estado: str | None = Query(default=None, description="ACTIVO, EGRESADO o FALLECIDO"),
    buscar: str | None = Query(default=None, description="Busca por nombre, apellido o codigo"),
):
    return [con_edad(p) for p in db.listar(estado=estado, buscar=buscar)]


@app.get("/pacientes/{codigo}", response_model=Paciente, tags=["Pacientes"])
def obtener_paciente(codigo: str):
    paciente = db.obtener_por_codigo(codigo)
    if paciente is None:
        raise HTTPException(status_code=404, detail="No existe un interno con ese código.")
    return con_edad(paciente)


@app.put("/pacientes/{codigo}", response_model=Paciente, tags=["Pacientes"])
def actualizar_paciente(codigo: str, datos: PacienteActualizar):
    """Actualiza los datos que si pueden cambiar durante la estadia."""
    cambios = datos.model_dump(exclude_unset=True)
    if not cambios:
        raise HTTPException(status_code=400, detail="No se enviaron campos por actualizar.")

    if cambios.get("estado") is None:
        cambios.pop("estado", None)
    if "estado" not in cambios:
        # Fecha y motivo de egreso solo viajan con el cambio de estado.
        cambios.pop("fecha_egreso", None)
        cambios.pop("motivo_egreso", None)
        if not cambios:
            raise HTTPException(status_code=400, detail="No se enviaron campos por actualizar.")
    else:
        actual = db.obtener_por_codigo(codigo)
        if actual is None:
            raise HTTPException(status_code=404, detail="No existe un interno con ese código.")
        cambios.update(datos_de_egreso(actual, cambios))

    paciente = db.actualizar(codigo, cambios)
    if paciente is None:
        raise HTTPException(status_code=404, detail="No existe un interno con ese código.")
    return con_edad(paciente)


@app.delete("/pacientes/{codigo}", status_code=204, tags=["Pacientes"])
def eliminar_paciente(codigo: str):
    """Elimina el registro de un anciano."""
    if not db.eliminar(codigo):
        raise HTTPException(status_code=404, detail="No existe un interno con ese código.")
