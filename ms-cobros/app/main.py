"""
Microservicio de Cobros y Descuentos de la Fundacion
Sistema para Administracion Asilo de Ancianos "Cabeza de Algodon"

Tarifas del asilo, cargos de citas, examenes y medicamentos con el
descuento de la fundacion, y estado de cuenta del familiar. Ademas, las
entradas y salidas del asilo: cuotas mensuales, donaciones, gastos y lo
que se le debe y se le paga a la fundacion. Capa de
presentacion: el calculo del dinero esta en reglas.py y el SQL en db.py.

Puerto: 8082
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query

from . import db
from .reglas import (
    a_decimal,
    calcular_montos,
    fecha_valida,
    periodo_valido,
    saldo_con_la_fundacion,
)
from .schemas import (
    Cargo,
    CargoCrear,
    Cuota,
    CuotaCrear,
    CuotasGeneradas,
    CuotasGenerar,
    DeudaFundacion,
    Donacion,
    DonacionCrear,
    EstadoCuenta,
    Gasto,
    GastoCrear,
    PagoFundacion,
    PagoFundacionCrear,
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

    Se verifica aqui para devolver un mensaje claro; la llave foranea de
    MySQL lo impide igual, por si alguien borra desde otro lado.
    """
    if db.obtener_tarifa(tarifa_id) is None:
        raise HTTPException(status_code=404, detail="La tarifa no existe.")

    if db.tarifa_tiene_cargos(tarifa_id):
        raise HTTPException(
            status_code=409,
            detail="La tarifa ya tiene cobros registrados. Desactívela en lugar de borrarla.",
        )

    db.eliminar_tarifa(tarifa_id)


# ---------------------------------------------------------------- cargos

@app.post("/cargos", response_model=Cargo, status_code=201, tags=["Cobros"])
def crear_cargo(datos: CargoCrear):
    """
    Genera un cargo a la cuenta del familiar aplicando el descuento de la fundacion.

    Lo llama ms-solicitudes cuando una solicitud se convierte en visita.
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


# =====================================================================
# Cuotas mensuales (RF-33)
# =====================================================================

def _periodo(texto: str) -> str:
    try:
        return periodo_valido(texto)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))


def _fecha(texto: str | None) -> str:
    try:
        return fecha_valida(texto).isoformat()
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))


@app.get("/cuotas", response_model=list[Cuota], tags=["Cuotas"])
def listar_cuotas(periodo: str | None = None, paciente_id: str | None = None,
                  estado: str | None = Query(default=None, description="PENDIENTE o PAGADA")):
    return db.listar_cuotas(periodo=periodo, paciente_id=paciente_id, estado=estado)


@app.post("/cuotas", response_model=Cuota, status_code=201, tags=["Cuotas"])
def crear_cuota(datos: CuotaCrear):
    """La cuota de un interno para un mes. Una sola por mes."""
    periodo = _periodo(datos.periodo)
    creadas, _ = db.crear_cuotas(periodo, str(a_decimal(datos.monto)), [datos.model_dump()])
    if not creadas:
        raise HTTPException(
            status_code=409, detail=f"Ese interno ya tiene registrada la cuota de {periodo}."
        )
    return db.obtener_cuota(creadas[0])


@app.post("/cuotas/generar", response_model=CuotasGeneradas, status_code=201, tags=["Cuotas"])
def generar_cuotas(datos: CuotasGenerar):
    """
    Las cuotas de un mes para todos los internos que manda la pantalla (los
    activos). Los que ya tenian la de ese mes se dejan como estaban.
    """
    periodo = _periodo(datos.periodo)
    creadas, repetidas = db.crear_cuotas(
        periodo, str(a_decimal(datos.monto)), [i.model_dump() for i in datos.internos]
    )
    return {
        "creadas": len(creadas),
        "ya_existian": repetidas,
        "cuotas": [db.obtener_cuota(c) for c in creadas],
    }


@app.post("/cuotas/{cuota_id}/pagar", response_model=Cuota, tags=["Cuotas"])
def pagar_cuota(cuota_id: int):
    if db.obtener_cuota(cuota_id) is None:
        raise HTTPException(status_code=404, detail="La cuota no existe.")
    if not db.pagar_cuota(cuota_id):
        raise HTTPException(status_code=409, detail="Esa cuota ya estaba pagada.")
    return db.obtener_cuota(cuota_id)


@app.delete("/cuotas/{cuota_id}", status_code=204, tags=["Cuotas"])
def anular_cuota(cuota_id: int):
    """Anula una cuota registrada por error, siempre que no este pagada."""
    if db.obtener_cuota(cuota_id) is None:
        raise HTTPException(status_code=404, detail="La cuota no existe.")
    if not db.anular_cuota(cuota_id):
        raise HTTPException(status_code=409, detail="No se puede anular una cuota ya pagada.")


# =====================================================================
# Donaciones y gastos (RF-34 y RF-35)
#
# No se borran ni se editan: son el registro con que se fiscaliza el
# dinero del asilo. Un error se corrige con un registro que lo explique.
# =====================================================================

def _registro(tabla: str, datos) -> dict:
    valores = datos.model_dump()
    valores["fecha"] = _fecha(valores.get("fecha"))
    valores["monto"] = str(a_decimal(valores["monto"]))
    for campo in ("origen", "descripcion", "comprobante"):
        if isinstance(valores.get(campo), str):
            valores[campo] = " ".join(valores[campo].split()) or None
    if tabla == "donaciones" and not valores["origen"]:
        raise HTTPException(status_code=422, detail="Indique quién hizo la donación.")
    if tabla == "gastos" and not valores["descripcion"]:
        raise HTTPException(status_code=422, detail="Describa en qué se gastó.")
    return db.registrar(tabla, valores)


@app.get("/donaciones", response_model=list[Donacion], tags=["Donaciones"])
def listar_donaciones(desde: str | None = None, hasta: str | None = None):
    return db.listar("donaciones", desde, hasta)


@app.post("/donaciones", response_model=Donacion, status_code=201, tags=["Donaciones"])
def registrar_donacion(datos: DonacionCrear):
    return _registro("donaciones", datos)


@app.get("/gastos", response_model=list[Gasto], tags=["Gastos"])
def listar_gastos(desde: str | None = None, hasta: str | None = None):
    return db.listar("gastos", desde, hasta)


@app.post("/gastos", response_model=Gasto, status_code=201, tags=["Gastos"])
def registrar_gasto(datos: GastoCrear):
    return _registro("gastos", datos)


# =====================================================================
# Cuenta con la fundacion (RF-36)
# =====================================================================

def _deuda() -> dict:
    totales = db.deuda_con_la_fundacion()
    saldo = saldo_con_la_fundacion(totales["total_servicios"], totales["total_pagado"])
    return {
        "total_servicios": float(totales["total_servicios"]),
        "consultas": float(totales["consultas"]),
        "examenes": float(totales["examenes"]),
        "medicamentos": float(totales["medicamentos"]),
        "total_pagado": float(totales["total_pagado"]),
        "saldo": float(saldo),
        "citas_por_cobrar": int(totales["citas_por_cobrar"]),
    }


@app.get("/fundacion/deuda", response_model=DeudaFundacion, tags=["Fundación"])
def deuda_con_la_fundacion():
    return _deuda()


@app.get("/fundacion/pagos", response_model=list[PagoFundacion], tags=["Fundación"])
def listar_pagos_fundacion(desde: str | None = None, hasta: str | None = None):
    return db.listar("pagos_fundacion", desde, hasta)


@app.post("/fundacion/pagos", response_model=PagoFundacion, status_code=201, tags=["Fundación"])
def registrar_pago_fundacion(datos: PagoFundacionCrear):
    """Un pago no puede pasar de lo que se debe: se pagaria de mas."""
    saldo = saldo_con_la_fundacion(*(
        db.deuda_con_la_fundacion()[c] for c in ("total_servicios", "total_pagado")
    ))
    if a_decimal(datos.monto) > saldo:
        raise HTTPException(
            status_code=422,
            detail=f"El pago (Q{a_decimal(datos.monto):,.2f}) es mayor que lo que se le debe "
                   f"a la fundación (Q{saldo:,.2f}).",
        )
    return _registro("pagos_fundacion", datos)
