"""
Microservicio de Cobros y Descuentos de la Fundacion
Sistema para Administracion Asilo de Ancianos "Cabeza de Algodon"

Responsabilidad unica: administrar las tarifas del asilo, generar los
cargos de citas, examenes y medicamentos aplicando el descuento de la
fundacion, y llevar el estado de cuenta que el familiar debe cancelar.

Puerto: 8082
Documentacion interactiva: http://localhost:8082/docs
"""

from datetime import datetime

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from .db import get_conn, init_db
from .reglas import calcular_montos
from .schemas import (
    Cargo,
    CargoCrear,
    EstadoCuenta,
    Tarifa,
    TarifaActualizar,
    TarifaCrear,
)

app = FastAPI(
    title="MS Cobros - Asilo Cabeza de Algodon",
    description=(
        "Microservicio encargado de las tarifas, el calculo de cobros con "
        "descuento de la fundacion y el estado de cuenta de los familiares."
    ),
    version="1.0.0",
)

# Permite que la aplicacion base (navegador) consuma este microservicio.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def al_iniciar() -> None:
    init_db()


def fila_a_cargo(fila) -> dict:
    """Convierte una fila de SQLite en el diccionario que espera el esquema Cargo."""
    cargo = dict(fila)
    cargo["cubierto_fundacion"] = bool(cargo["cubierto_fundacion"])
    return cargo


# ---------------------------------------------------------------- salud


@app.get("/health", tags=["Estado"])
def health() -> dict:
    """Verifica que el microservicio y su base de datos respondan."""
    conn = get_conn()
    tarifas = conn.execute("SELECT COUNT(*) AS n FROM tarifas").fetchone()["n"]
    conn.close()
    return {"servicio": "ms-cobros", "estado": "arriba", "tarifas_registradas": tarifas}


# --------------------------------------------------------------- CRUD tarifas


@app.get("/tarifas", response_model=list[Tarifa], tags=["Tarifas"])
def listar_tarifas(tipo: str | None = None, solo_activas: bool = False):
    """Lista el tarifario del asilo, opcionalmente filtrado por tipo."""
    sql = "SELECT * FROM tarifas WHERE 1 = 1"
    params: list = []
    if tipo:
        sql += " AND tipo = ?"
        params.append(tipo.upper())
    if solo_activas:
        sql += " AND activo = 1"
    sql += " ORDER BY tipo, concepto"

    conn = get_conn()
    filas = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(f) for f in filas]


@app.get("/tarifas/{tarifa_id}", response_model=Tarifa, tags=["Tarifas"])
def obtener_tarifa(tarifa_id: int):
    conn = get_conn()
    fila = conn.execute("SELECT * FROM tarifas WHERE id = ?", (tarifa_id,)).fetchone()
    conn.close()
    if fila is None:
        raise HTTPException(status_code=404, detail="La tarifa no existe.")
    return dict(fila)


@app.post("/tarifas", response_model=Tarifa, status_code=201, tags=["Tarifas"])
def crear_tarifa(datos: TarifaCrear):
    """Registra un nuevo concepto cobrable (cita, examen o medicamento)."""
    conn = get_conn()
    with conn:
        cursor = conn.execute(
            """INSERT INTO tarifas (concepto, tipo, precio, descuento_fundacion, activo)
               VALUES (?, ?, ?, ?, ?)""",
            (
                datos.concepto,
                datos.tipo,
                datos.precio,
                datos.descuento_fundacion,
                int(datos.activo),
            ),
        )
        nuevo_id = cursor.lastrowid
        fila = conn.execute("SELECT * FROM tarifas WHERE id = ?", (nuevo_id,)).fetchone()
    conn.close()
    return dict(fila)


@app.put("/tarifas/{tarifa_id}", response_model=Tarifa, tags=["Tarifas"])
def actualizar_tarifa(tarifa_id: int, datos: TarifaActualizar):
    """Actualiza precio, descuento o estado de una tarifa existente."""
    cambios = datos.model_dump(exclude_unset=True)
    if not cambios:
        raise HTTPException(status_code=400, detail="No se enviaron campos por actualizar.")
    if "activo" in cambios:
        cambios["activo"] = int(cambios["activo"])

    conn = get_conn()
    existe = conn.execute("SELECT id FROM tarifas WHERE id = ?", (tarifa_id,)).fetchone()
    if existe is None:
        conn.close()
        raise HTTPException(status_code=404, detail="La tarifa no existe.")

    asignaciones = ", ".join(f"{campo} = ?" for campo in cambios)
    with conn:
        conn.execute(
            f"UPDATE tarifas SET {asignaciones} WHERE id = ?",
            [*cambios.values(), tarifa_id],
        )
        fila = conn.execute("SELECT * FROM tarifas WHERE id = ?", (tarifa_id,)).fetchone()
    conn.close()
    return dict(fila)


@app.delete("/tarifas/{tarifa_id}", status_code=204, tags=["Tarifas"])
def eliminar_tarifa(tarifa_id: int):
    """Elimina una tarifa que aun no tenga cobros asociados."""
    conn = get_conn()
    existe = conn.execute("SELECT id FROM tarifas WHERE id = ?", (tarifa_id,)).fetchone()
    if existe is None:
        conn.close()
        raise HTTPException(status_code=404, detail="La tarifa no existe.")

    usada = conn.execute(
        "SELECT COUNT(*) AS n FROM cargos WHERE tarifa_id = ?", (tarifa_id,)
    ).fetchone()["n"]
    if usada:
        conn.close()
        raise HTTPException(
            status_code=409,
            detail="La tarifa ya tiene cobros registrados. Desactivela en lugar de borrarla.",
        )

    with conn:
        conn.execute("DELETE FROM tarifas WHERE id = ?", (tarifa_id,))
    conn.close()


# ---------------------------------------------------------------- cargos


@app.post("/cargos", response_model=Cargo, status_code=201, tags=["Cobros"])
def crear_cargo(datos: CargoCrear):
    """
    Genera un cargo a la cuenta del familiar aplicando el descuento de la fundacion.

    Este es el endpoint que consume el microservicio de Solicitudes cuando
    una solicitud se convierte en visita medica formal.
    """
    conn = get_conn()

    if datos.tarifa_id is not None:
        tarifa = conn.execute(
            "SELECT * FROM tarifas WHERE id = ? AND activo = 1", (datos.tarifa_id,)
        ).fetchone()
    else:
        tarifa = conn.execute(
            "SELECT * FROM tarifas WHERE tipo = ? AND activo = 1 ORDER BY precio LIMIT 1",
            (datos.tipo,),
        ).fetchone()

    if tarifa is None:
        conn.close()
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

    with conn:
        cursor = conn.execute(
            """INSERT INTO cargos (
                   paciente_id, paciente_nombre, familiar_email, tarifa_id, concepto,
                   tipo, cantidad, monto_bruto, descuento_aplicado, monto_neto,
                   cubierto_fundacion, estado, referencia, fecha)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDIENTE', ?, ?)""",
            (
                datos.paciente_id,
                datos.paciente_nombre,
                datos.familiar_email,
                tarifa["id"],
                tarifa["concepto"],
                tarifa["tipo"],
                datos.cantidad,
                montos["monto_bruto"],
                montos["descuento_aplicado"],
                montos["monto_neto"],
                int(datos.cubierto_fundacion),
                datos.referencia,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        fila = conn.execute(
            "SELECT * FROM cargos WHERE id = ?", (cursor.lastrowid,)
        ).fetchone()
    conn.close()
    return fila_a_cargo(fila)


@app.get("/cargos", response_model=list[Cargo], tags=["Cobros"])
def listar_cargos(
    paciente_id: str | None = Query(default=None),
    estado: str | None = Query(default=None, description="PENDIENTE o PAGADO"),
):
    sql = "SELECT * FROM cargos WHERE 1 = 1"
    params: list = []
    if paciente_id:
        sql += " AND paciente_id = ?"
        params.append(paciente_id)
    if estado:
        sql += " AND estado = ?"
        params.append(estado.upper())
    sql += " ORDER BY id DESC"

    conn = get_conn()
    filas = conn.execute(sql, params).fetchall()
    conn.close()
    return [fila_a_cargo(f) for f in filas]


@app.post("/cargos/{cargo_id}/pagar", response_model=Cargo, tags=["Cobros"])
def pagar_cargo(cargo_id: int):
    """Marca como cancelado un cargo pendiente del familiar."""
    conn = get_conn()
    fila = conn.execute("SELECT * FROM cargos WHERE id = ?", (cargo_id,)).fetchone()
    if fila is None:
        conn.close()
        raise HTTPException(status_code=404, detail="El cargo no existe.")
    if fila["estado"] == "PAGADO":
        conn.close()
        raise HTTPException(status_code=409, detail="Este cargo ya estaba cancelado.")

    with conn:
        conn.execute("UPDATE cargos SET estado = 'PAGADO' WHERE id = ?", (cargo_id,))
        fila = conn.execute("SELECT * FROM cargos WHERE id = ?", (cargo_id,)).fetchone()
    conn.close()
    return fila_a_cargo(fila)


@app.delete("/cargos/{cargo_id}", status_code=204, tags=["Cobros"])
def anular_cargo(cargo_id: int):
    """Anula un cargo registrado por error, siempre que aun no este pagado."""
    conn = get_conn()
    fila = conn.execute("SELECT * FROM cargos WHERE id = ?", (cargo_id,)).fetchone()
    if fila is None:
        conn.close()
        raise HTTPException(status_code=404, detail="El cargo no existe.")
    if fila["estado"] == "PAGADO":
        conn.close()
        raise HTTPException(
            status_code=409, detail="No se puede anular un cargo ya cancelado."
        )
    with conn:
        conn.execute("DELETE FROM cargos WHERE id = ?", (cargo_id,))
    conn.close()


@app.get("/estado-cuenta/{paciente_id}", response_model=EstadoCuenta, tags=["Cobros"])
def estado_cuenta(paciente_id: str):
    """
    Devuelve el corte de cuenta del paciente: cuanto se cobro, cuanto
    cubrio la fundacion y cuanto queda pendiente de cancelar.
    """
    conn = get_conn()
    filas = conn.execute(
        "SELECT * FROM cargos WHERE paciente_id = ? ORDER BY id DESC", (paciente_id,)
    ).fetchall()
    conn.close()

    cargos = [fila_a_cargo(f) for f in filas]
    total_bruto = round(sum(c["monto_bruto"] for c in cargos), 2)
    total_descuento = round(sum(c["descuento_aplicado"] for c in cargos), 2)
    total_neto = round(sum(c["monto_neto"] for c in cargos), 2)
    total_pagado = round(
        sum(c["monto_neto"] for c in cargos if c["estado"] == "PAGADO"), 2
    )

    return {
        "paciente_id": paciente_id,
        "paciente_nombre": cargos[0]["paciente_nombre"] if cargos else None,
        "familiar_email": cargos[0]["familiar_email"] if cargos else None,
        "cantidad_cargos": len(cargos),
        "total_bruto": total_bruto,
        "total_descuento_fundacion": total_descuento,
        "total_neto": total_neto,
        "total_pagado": total_pagado,
        "saldo_pendiente": round(total_neto - total_pagado, 2),
        "cargos": cargos,
    }
