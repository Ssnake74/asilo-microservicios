"""
Microservicio de Cobros y Descuentos de la Fundacion
Sistema para Administracion Asilo de Ancianos "Cabeza de Algodon"

Responsabilidad unica: administrar las tarifas del asilo, generar los
cargos de citas, examenes y medicamentos aplicando el descuento de la
fundacion, y llevar el estado de cuenta que el familiar debe cancelar.

Capa de presentacion/controlador: recibe HTTP, decide y responde. El
calculo del dinero esta en reglas.py y el SQL en db.py.

Puerto: 8082
Documentacion interactiva: http://localhost:8082/docs
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from . import db
from .reglas import calcular_montos
from .schemas import (
    Cargo,
    CargoCrear,
    EstadoCuenta,
    Tarifa,
    TarifaActualizar,
    TarifaCrear,
)


@asynccontextmanager
async def ciclo_de_vida(app: FastAPI):
    db.init_db()
    yield


app = FastAPI(
    title="MS Cobros - Asilo Cabeza de Algodon",
    description=(
        "Microservicio encargado de las tarifas, el calculo de cobros con "
        "descuento de la fundacion y el estado de cuenta de los familiares."
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
        "servicio": "ms-cobros",
        "estado": "arriba",
        "motor": "MySQL",
        "tarifas_registradas": db.contar_tarifas(),
    }


# --------------------------------------------------------------- tarifas

@app.get("/tarifas", response_model=list[Tarifa], tags=["Tarifas"])
def listar_tarifas(tipo: str | None = None, solo_activas: bool = False):
    """Lista el tarifario del asilo, opcionalmente filtrado por tipo."""
    return db.listar_tarifas(tipo=tipo, solo_activas=solo_activas)


@app.get("/tarifas/{tarifa_id}", response_model=Tarifa, tags=["Tarifas"])
def obtener_tarifa(tarifa_id: int):
    tarifa = db.obtener_tarifa(tarifa_id)
    if tarifa is None:
        raise HTTPException(status_code=404, detail="La tarifa no existe.")
    return tarifa


@app.post("/tarifas", response_model=Tarifa, status_code=201, tags=["Tarifas"])
def crear_tarifa(datos: TarifaCrear):
    """Registra un nuevo concepto cobrable (cita, examen o medicamento)."""
    return db.crear_tarifa(datos.model_dump())


@app.put("/tarifas/{tarifa_id}", response_model=Tarifa, tags=["Tarifas"])
def actualizar_tarifa(tarifa_id: int, datos: TarifaActualizar):
    """Actualiza precio, descuento o estado de una tarifa existente."""
    cambios = datos.model_dump(exclude_unset=True)
    if not cambios:
        raise HTTPException(status_code=400, detail="No se enviaron campos por actualizar.")

    tarifa = db.actualizar_tarifa(tarifa_id, cambios)
    if tarifa is None:
        raise HTTPException(status_code=404, detail="La tarifa no existe.")
    return tarifa


@app.delete("/tarifas/{tarifa_id}", status_code=204, tags=["Tarifas"])
def eliminar_tarifa(tarifa_id: int):
    """
    Elimina una tarifa que aun no tenga cobros asociados.

    La verificacion se hace aqui para poder devolver un mensaje claro.
    Aun asi, la llave foranea de MySQL lo impediria de todos modos: es
    una segunda barrera por si alguien borra desde otro lado.
    """
    if db.obtener_tarifa(tarifa_id) is None:
        raise HTTPException(status_code=404, detail="La tarifa no existe.")

    if db.tarifa_tiene_cargos(tarifa_id):
        raise HTTPException(
            status_code=409,
            detail="La tarifa ya tiene cobros registrados. Desactivela en lugar de borrarla.",
        )

    db.eliminar_tarifa(tarifa_id)


# ---------------------------------------------------------------- cargos

@app.post("/cargos", response_model=Cargo, status_code=201, tags=["Cobros"])
def crear_cargo(datos: CargoCrear):
    """
    Genera un cargo a la cuenta del familiar aplicando el descuento de la fundacion.

    Este es el endpoint que consume el microservicio de Solicitudes cuando
    una solicitud se convierte en visita medica formal.
    """
    tarifa = db.buscar_tarifa_para_cargo(datos.tarifa_id, datos.tipo)
    if tarifa is None:
        raise HTTPException(
            status_code=404,
            detail="No hay una tarifa activa que corresponda al cargo solicitado.",
        )

    montos = calcular_montos(
        precio=tarifa["precio"],
        cantidad=datos.cantidad,
        descuento_fundacion=tarifa["descuento_fundacion"],
        cubierto_fundacion=datos.cubierto_fundacion,
    )

    return db.crear_cargo(datos.model_dump(), tarifa, montos)


@app.get("/cargos", response_model=list[Cargo], tags=["Cobros"])
def listar_cargos(
    paciente_id: str | None = Query(default=None),
    estado: str | None = Query(default=None, description="PENDIENTE o PAGADO"),
):
    return db.listar_cargos(paciente_id=paciente_id, estado=estado)


@app.post("/cargos/{cargo_id}/pagar", response_model=Cargo, tags=["Cobros"])
def pagar_cargo(cargo_id: int):
    """Marca como cancelado un cargo pendiente del familiar."""
    cargo = db.obtener_cargo(cargo_id)
    if cargo is None:
        raise HTTPException(status_code=404, detail="El cargo no existe.")
    if cargo["estado"] == "PAGADO":
        raise HTTPException(status_code=409, detail="Este cargo ya estaba cancelado.")

    return db.marcar_pagado(cargo_id)


@app.delete("/cargos/{cargo_id}", status_code=204, tags=["Cobros"])
def anular_cargo(cargo_id: int):
    """Anula un cargo registrado por error, siempre que aun no este pagado."""
    cargo = db.obtener_cargo(cargo_id)
    if cargo is None:
        raise HTTPException(status_code=404, detail="El cargo no existe.")
    if cargo["estado"] == "PAGADO":
        raise HTTPException(
            status_code=409, detail="No se puede anular un cargo ya cancelado."
        )

    db.eliminar_cargo(cargo_id)


@app.get("/estado-cuenta/{paciente_id}", response_model=EstadoCuenta, tags=["Cobros"])
def estado_cuenta(paciente_id: str):
    """
    Devuelve el corte de cuenta del paciente: cuanto se cobro, cuanto
    cubrio la fundacion y cuanto queda pendiente de cancelar.
    """
    resumen = db.totales_paciente(paciente_id)
    resumen["paciente_id"] = paciente_id
    resumen["cargos"] = db.listar_cargos(paciente_id=paciente_id)
    return resumen
