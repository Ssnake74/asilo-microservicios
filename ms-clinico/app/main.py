"""
Microservicio Clinico
Sistema para Administracion Asilo de Ancianos "Cabeza de Algodon"

Lo que pasa dentro de la visita medica y despues de ella:

  - el especialista llena la ficha con el diagnostico (RF-21), ordena
    examenes (RF-22) y receta medicamentos (RF-24);
  - el laboratorio registra el resultado de cada examen (RF-23);
  - la farmacia registra el despacho de cada receta (RF-25);
  - el historial del interno junta todas sus fichas (RF-26).

Al registrar un resultado o un despacho le pide a ms-cobros el cargo
correspondiente (RF-29). Capa de presentacion: el SQL vive en db.py.

Quien registra lo dice el gateway en el encabezado X-Usuario. Los
microservicios no son alcanzables desde fuera (RNF-03), asi que ese
encabezado solo puede ponerlo el gateway.

Puerto: 8085
"""

import asyncio
import os
from contextlib import asynccontextmanager
from urllib.parse import unquote

from fastapi import FastAPI, Header, HTTPException, Query

from . import clientes, db
from .reglas import (
    PENDIENTE,
    cantidad_de_despacho_valida,
    referencia_examen,
    referencia_receta,
    texto_limpio,
)
from .schemas import (
    ConCobro,
    DespachoCrear,
    Ficha,
    FichaCrear,
    Orden,
    OrdenCrear,
    Receta,
    RecetaCrear,
    ResultadoCrear,
)


# ---------------------------------------------------------------------
# Reintento de los cobros pendientes (RNF-13)
#
# Igual que en ms-solicitudes: cada tantos segundos se cobran los
# resultados y despachos que quedaron sin cargo porque cobros no
# respondia. Solo los que ya estaban pendientes en la vuelta anterior, para
# no cobrar dos veces uno que se esta registrando en este momento.
# ---------------------------------------------------------------------

SEGUNDOS_ENTRE_REINTENTOS = float(os.getenv("REINTENTO_SEGUNDOS", "15"))


def reintentar_cobros(vistos_antes: set[str]) -> set[str]:
    ordenes = db.ordenes_sin_cargo()
    despachos = db.despachos_sin_cargo()
    vistos_ahora = {f"o{o['id']}" for o in ordenes} | {f"d{d['id']}" for d in despachos}
    if not vistos_ahora or not clientes.cobros_responde():
        return vistos_ahora
    for orden in ordenes:
        if f"o{orden['id']}" in vistos_antes:
            cargo_id, _ = clientes.generar_cargo(
                orden, "EXAMEN", orden["tarifa_id"], 1, referencia_examen(orden["id"]),
                f"El examen «{orden['examen']}»",
            )
            if cargo_id is not None:
                db.anotar_cargo_de_orden(orden["id"], cargo_id)
                vistos_ahora.discard(f"o{orden['id']}")
    for despacho in despachos:
        if f"d{despacho['id']}" in vistos_antes:
            cargo_id, _ = clientes.generar_cargo(
                despacho, "MEDICAMENTO", despacho["tarifa_id"], despacho["cantidad_despachada"],
                referencia_receta(despacho["receta_id"]), f"El medicamento «{despacho['medicamento']}»",
            )
            if cargo_id is not None:
                db.anotar_cargo_de_despacho(despacho["id"], cargo_id)
                vistos_ahora.discard(f"d{despacho['id']}")
    return vistos_ahora


async def bucle_de_reintentos() -> None:
    vistos: set[str] = set()
    while True:
        await asyncio.sleep(SEGUNDOS_ENTRE_REINTENTOS)
        try:
            vistos = await asyncio.to_thread(reintentar_cobros, vistos)
        except Exception as error:
            print(f"[ms-clinico] Reintento de cobros fallido: {error}", flush=True)


@asynccontextmanager
async def ciclo_de_vida(app: FastAPI):
    db.init_db()
    tarea = asyncio.create_task(bucle_de_reintentos())
    yield
    tarea.cancel()


app = FastAPI(
    title="MS Clinico - Asilo Cabeza de Algodon",
    description="Ficha médica, órdenes de examen, resultados, recetas y despachos.",
    version="1.0.0",
    lifespan=ciclo_de_vida,
)


def quien(x_usuario: str | None) -> str | None:
    """El nombre de quien registra; el gateway lo manda codificado para no perder las tildes."""
    return unquote(x_usuario) if x_usuario else None


def no_disponible(error: clientes.NoDisponible) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail=f"El módulo de {error.modulo} no está disponible en este momento.",
    )


def ficha_o_error(ficha_id: int) -> dict:
    ficha = db.obtener_ficha_simple(ficha_id)
    if ficha is None:
        raise HTTPException(status_code=404, detail="La ficha médica no existe.")
    return ficha


# ---------------------------------------------------------------- salud

@app.get("/health", tags=["Estado"])
def health() -> dict:
    return {"servicio": "ms-clinico", "estado": "arriba", "motor": "MySQL", **db.contar_pendientes()}


# ---------------------------------------------------------------- fichas

@app.get("/fichas", response_model=list[Ficha], tags=["Fichas"])
def listar_fichas(paciente_id: str | None = None, visita_id: int | None = None):
    """Con paciente_id es el historial medico del interno (RF-26)."""
    return db.listar_fichas(paciente_id=paciente_id, visita_id=visita_id)


@app.get("/fichas/{ficha_id}", response_model=Ficha, tags=["Fichas"])
def obtener_ficha(ficha_id: int):
    ficha = db.obtener_ficha(ficha_id)
    if ficha is None:
        raise HTTPException(status_code=404, detail="La ficha médica no existe.")
    return ficha


@app.post("/fichas", response_model=Ficha, status_code=201, tags=["Fichas"])
def crear_ficha(datos: FichaCrear, x_usuario: str | None = Header(default=None)):
    """
    El especialista registra lo que encontro en la visita (RF-21). Una
    visita tiene una sola ficha: lo que falte se agrega como examen o receta.
    """
    diagnostico = texto_limpio(datos.diagnostico)
    if diagnostico is None or len(diagnostico) < 5:
        raise HTTPException(status_code=422, detail="Escriba el diagnóstico de la visita.")
    try:
        visita = clientes.visita_con_su_remision(datos.visita_id)
    except clientes.NoDisponible as error:
        raise no_disponible(error)
    if visita is None:
        raise HTTPException(status_code=422, detail="La visita indicada no existe.")
    try:
        ficha_id = db.crear_ficha(visita, diagnostico, texto_limpio(datos.observaciones), quien(x_usuario))
    except db.YaExiste:
        raise HTTPException(status_code=409, detail="Esa visita ya tiene su ficha médica.")
    return db.obtener_ficha(ficha_id)


# ------------------------------------------------ examenes y resultados

@app.get("/examenes", response_model=list[Orden], tags=["Laboratorio"])
def listar_examenes(
    estado: str | None = Query(default=None, description="PENDIENTE o COMPLETADA"),
    paciente_id: str | None = None,
):
    return db.listar_ordenes(estado=estado, paciente_id=paciente_id)


@app.post("/examenes", response_model=Orden, status_code=201, tags=["Laboratorio"])
def ordenar_examen(datos: OrdenCrear):
    """El especialista ordena un examen del catalogo dentro de la ficha (RF-22)."""
    ficha_o_error(datos.ficha_id)
    try:
        examen = clientes.examen(datos.tipo_examen_id)
    except clientes.NoDisponible as error:
        raise no_disponible(error)
    if examen is None or not examen["activo"]:
        raise HTTPException(
            status_code=422, detail="El examen elegido no existe en el catálogo o ya no se hace."
        )
    orden_id = db.crear_orden(datos.ficha_id, examen, texto_limpio(datos.indicaciones))
    return db.obtener_orden(orden_id)


@app.post("/resultados", response_model=ConCobro, status_code=201, tags=["Laboratorio"])
def registrar_resultado(datos: ResultadoCrear, x_usuario: str | None = Header(default=None)):
    """
    El laboratorio registra el resultado (RF-23) y el examen se cobra
    (RF-29): se cobra lo que se hizo, no lo que se ordeno.
    """
    orden = db.obtener_orden(datos.orden_id)
    if orden is None:
        raise HTTPException(status_code=404, detail="La orden de examen no existe.")
    resultado = texto_limpio(datos.resultado)
    if resultado is None or len(resultado) < 3:
        raise HTTPException(status_code=422, detail="Escriba el resultado del examen.")
    if orden["estado"] != PENDIENTE or not db.registrar_resultado(datos.orden_id, resultado, quien(x_usuario)):
        raise HTTPException(status_code=409, detail="Ese examen ya tiene su resultado.")

    ficha = db.obtener_ficha_simple(orden["ficha_id"])
    cargo_id, mensaje = clientes.generar_cargo(
        ficha, "EXAMEN", orden["tarifa_id"], 1, referencia_examen(datos.orden_id),
        f"El examen «{orden['examen']}»",
    )
    db.anotar_cargo_de_orden(datos.orden_id, cargo_id)
    return {"orden": db.obtener_orden(datos.orden_id), "mensaje_cobro": mensaje}


# ------------------------------------------------- recetas y despachos

@app.get("/recetas", response_model=list[Receta], tags=["Farmacia"])
def listar_recetas(
    estado: str | None = Query(default=None, description="PENDIENTE o DESPACHADA"),
    paciente_id: str | None = None,
):
    return db.listar_recetas(estado=estado, paciente_id=paciente_id)


@app.post("/recetas", response_model=Receta, status_code=201, tags=["Farmacia"])
def recetar(datos: RecetaCrear):
    """El especialista receta un medicamento con cantidad y tiempo de aplicacion (RF-24)."""
    ficha_o_error(datos.ficha_id)
    indicaciones = texto_limpio(datos.indicaciones)
    if indicaciones is None or len(indicaciones) < 5:
        raise HTTPException(
            status_code=422, detail="Indique cómo y por cuánto tiempo se aplica el medicamento."
        )
    try:
        medicamento = clientes.medicamento(datos.medicamento_id)
    except clientes.NoDisponible as error:
        raise no_disponible(error)
    if medicamento is None or not medicamento["activo"]:
        raise HTTPException(
            status_code=422,
            detail="El medicamento elegido no existe en el catálogo o ya no se receta.",
        )
    receta_id = db.crear_receta(datos.ficha_id, medicamento, datos.cantidad, indicaciones)
    return db.obtener_receta(receta_id)


@app.post("/despachos", response_model=ConCobro, status_code=201, tags=["Farmacia"])
def despachar(datos: DespachoCrear, x_usuario: str | None = Header(default=None)):
    """
    La farmacia registra la entrega (RF-25) y se cobra lo entregado
    (RF-29). Puede entregar menos de lo recetado si no tiene existencia,
    nunca mas; una receta se despacha una sola vez.
    """
    receta = db.obtener_receta(datos.receta_id)
    if receta is None:
        raise HTTPException(status_code=404, detail="La receta no existe.")
    if receta["estado"] != PENDIENTE:
        raise HTTPException(status_code=409, detail="Esa receta ya fue despachada.")
    if not cantidad_de_despacho_valida(datos.cantidad, receta["cantidad"]):
        raise HTTPException(
            status_code=422,
            detail=f"Se recetaron {receta['cantidad']}: no se puede entregar más de eso.",
        )
    despacho_id = db.registrar_despacho(datos.receta_id, datos.cantidad, quien(x_usuario))
    if despacho_id is None:
        raise HTTPException(status_code=409, detail="Esa receta ya fue despachada.")

    ficha = db.obtener_ficha_simple(receta["ficha_id"])
    cargo_id, mensaje = clientes.generar_cargo(
        ficha, "MEDICAMENTO", receta["tarifa_id"], datos.cantidad, referencia_receta(datos.receta_id),
        f"El medicamento «{receta['medicamento']}»",
    )
    db.anotar_cargo_de_despacho(despacho_id, cargo_id)
    return {"receta": db.obtener_receta(datos.receta_id), "mensaje_cobro": mensaje}
