"""
H · Cobros (CU-10 a CU-14)

El dinero se verifica al centavo. Por eso las pruebas usan tarifas
propias con precios elegidos a proposito, en vez de las del tarifario
real, que alguien puede cambiar en cualquier momento:

  Q250.00 al 40 %   el ejemplo del enunciado: Q150 neto
  Q5.35   al 50 %   da un descuento de 2.675 exacto: debe quedar 2.68
  Q2.01   al 50 %   da 1.005: la trampa clasica del punto flotante, donde
                    round(1.005, 2) da 1.0 en vez de 1.01
  Q33.33  al 15 %   multiplicado por cantidades, para cuadrar totales

Ninguna tarifa de prueba lleva la palabra "especialista" en el nombre: es
la que busca ms-solicitudes para cobrar las visitas, y no hay que
desviarle la eleccion a los demas grupos.
"""

from apoyo.contexto import dinero, montos_esperados, q
from apoyo.gateway import resumen

LETRA = "H"
TITULO = "Cobros"
DESCRIPCION = "Cálculo del cargo, redondeo, límites de tarifa y cantidad, pagos y estado de cuenta."


def montos(cargo: dict) -> str:
    return (
        f"bruto {q(cargo['monto_bruto'])}, descuento {q(cargo['descuento_aplicado'])}, "
        f"neto {q(cargo['monto_neto'])}"
    )


def coincide(cargo: dict, bruto: str, descuento: str, neto: str) -> bool:
    return (
        dinero(cargo["monto_bruto"]) == dinero(bruto)
        and dinero(cargo["descuento_aplicado"]) == dinero(descuento)
        and dinero(cargo["monto_neto"]) == dinero(neto)
    )


def ejecutar(ctx) -> None:
    rep, gw = ctx.rep, ctx.gw

    t250 = ctx.tarifa("H consulta Q250 al 40 %", "CITA", 250.00, 40)
    t535 = ctx.tarifa("H redondeo Q5.35 al 50 %", "EXAMEN", 5.35, 50)
    t201 = ctx.tarifa("H redondeo Q2.01 al 50 %", "EXAMEN", 2.01, 50)
    t3333 = ctx.tarifa("H varios Q33.33 al 15 %", "MEDICAMENTO", 33.33, 15)
    cargo_pagable = None
    tarifa_sin_cargos = None

    with rep.caso(
        "Consulta de Q250 con 40 % de la fundación",
        "RN-09",
        "Bruto Q250.00, descuento Q100.00, neto Q150.00",
    ) as c:
        r = ctx.crear_cargo(ctx.cuenta_de_prueba("H1"), t250, beneficiario=True)
        c.obtenido = montos(r.json()) if r.status_code == 201 else resumen(r)
        c.pasa = r.status_code == 201 and coincide(r.json(), "250.00", "100.00", "150.00")
        if r.status_code == 201:
            cargo_pagable = r.json()

    with rep.caso(
        "La misma consulta para un interno no beneficiario",
        "RN-09 (el descuento solo aplica a beneficiarios)",
        "Bruto Q250.00, descuento Q0.00, neto Q250.00",
    ) as c:
        r = ctx.crear_cargo(ctx.cuenta_de_prueba("H2"), t250, beneficiario=False)
        c.obtenido = montos(r.json()) if r.status_code == 201 else resumen(r)
        c.pasa = r.status_code == 201 and coincide(r.json(), "250.00", "0.00", "250.00")

    with rep.caso(
        "Redondeo comercial a dos decimales",
        "RN-10",
        "Q5.35 al 50 %: el descuento de 2.675 queda en Q2.68 (no 2.67) y el neto en "
        "Q2.67. Q2.01 al 50 %: 1.005 queda en Q1.01 (no 1.00) y el neto en Q1.00",
    ) as c:
        r1 = ctx.crear_cargo(ctx.cuenta_de_prueba("H3"), t535)
        r2 = ctx.crear_cargo(ctx.cuenta_de_prueba("H3"), t201)
        c.obtenido = (
            f"Q5.35 al 50 %: {montos(r1.json()) if r1.status_code == 201 else resumen(r1)}\n"
            f"Q2.01 al 50 %: {montos(r2.json()) if r2.status_code == 201 else resumen(r2)}"
        )
        c.pasa = (
            r1.status_code == 201 and coincide(r1.json(), "5.35", "2.68", "2.67")
            and r2.status_code == 201 and coincide(r2.json(), "2.01", "1.01", "1.00")
        )

    with rep.caso(
        "Porcentaje de descuento fuera de 0 a 100",
        "RN-13",
        "422 para 101 y para −1 al crear, y para 150 al editar; 0 y 100 se aceptan",
    ) as c:
        r101 = ctx.crear_tarifa("H descuento 101", "EXAMEN", 10, 101)
        rneg = ctx.crear_tarifa("H descuento -1", "EXAMEN", 10, -1)
        r150 = gw.put("CAJA", f"/api/tarifas/{t250['id']}", json={"descuento_fundacion": 150})
        r0 = ctx.crear_tarifa("H descuento 0", "EXAMEN", 10, 0)
        r100 = ctx.crear_tarifa("H descuento 100", "EXAMEN", 10, 100)
        c.obtenido = (
            f"crear con 101: {resumen(r101)}\ncrear con −1: {resumen(rneg)}\n"
            f"editar a 150: {resumen(r150)}\ncrear con 0: {r0.status_code} · "
            f"crear con 100: {r100.status_code}"
        )
        c.pasa = (
            r101.status_code == 422 and rneg.status_code == 422 and r150.status_code == 422
            and r0.status_code == 201 and r100.status_code == 201
        )

    with rep.caso(
        "Precio de la tarifa igual o menor que cero",
        "RN-14",
        "422 para Q0.00 y para −Q5.00; Q0.01 se acepta",
    ) as c:
        r0 = ctx.crear_tarifa("H precio 0", "EXAMEN", 0, 0)
        rneg = ctx.crear_tarifa("H precio -5", "EXAMEN", -5, 0)
        rmin = ctx.crear_tarifa("H precio 0.01", "EXAMEN", 0.01, 0)
        if rmin.status_code == 201:
            tarifa_sin_cargos = rmin.json()
        c.obtenido = f"Q0.00: {resumen(r0)}\n−Q5.00: {resumen(rneg)}\nQ0.01: {rmin.status_code}"
        c.pasa = r0.status_code == 422 and rneg.status_code == 422 and rmin.status_code == 201

    with rep.caso(
        "Cantidad del cargo fuera de 1 a 100",
        "RN-15",
        "422 para 0 y para 101; 1 y 100 se aceptan, y 100 × Q33.33 al 15 % da "
        "bruto Q3,333.00, descuento Q499.95, neto Q2,833.05",
    ) as c:
        cuenta = ctx.cuenta_de_prueba("H4")
        r0 = ctx.crear_cargo(cuenta, t3333, cantidad=0)
        r101 = ctx.crear_cargo(cuenta, t3333, cantidad=101)
        r1 = ctx.crear_cargo(cuenta, t3333, cantidad=1)
        r100 = ctx.crear_cargo(cuenta, t3333, cantidad=100)
        c.obtenido = (
            f"cantidad 0: {resumen(r0)}\ncantidad 101: {resumen(r101)}\n"
            f"cantidad 1: {r1.status_code} · cantidad 100: "
            f"{montos(r100.json()) if r100.status_code == 201 else resumen(r100)}"
        )
        c.pasa = (
            r0.status_code == 422 and r101.status_code == 422 and r1.status_code == 201
            and r100.status_code == 201 and coincide(r100.json(), "3333.00", "499.95", "2833.05")
        )

    with rep.caso(
        "Eliminar una tarifa que ya tiene cargos",
        "RN-11",
        "409 para la tarifa con cargos; 204 para una tarifa sin cargos",
    ) as c:
        con_cargos = gw.delete("CAJA", f"/api/tarifas/{t250['id']}")
        sin_cargos = (
            gw.delete("CAJA", f"/api/tarifas/{tarifa_sin_cargos['id']}") if tarifa_sin_cargos else None
        )
        c.obtenido = (
            f"con cargos: {resumen(con_cargos)} · sin cargos: "
            f"{sin_cargos.status_code if sin_cargos is not None else 'no se pudo crear la tarifa'}"
        )
        c.pasa = con_cargos.status_code == 409 and sin_cargos is not None and sin_cargos.status_code == 204

    with rep.caso(
        "Pagar dos veces el mismo cargo",
        "RN-12",
        "El primer pago 200 con estado PAGADO; el segundo 409",
    ) as c:
        if cargo_pagable is None:
            raise RuntimeError("no se creó el cargo del primer caso")
        p1 = gw.post("CAJA", f"/api/cargos/{cargo_pagable['id']}/pagar")
        p2 = gw.post("CAJA", f"/api/cargos/{cargo_pagable['id']}/pagar")
        estado = p1.json().get("estado") if p1.status_code == 200 else None
        c.obtenido = f"primer pago: {p1.status_code} ({estado}) · segundo pago: {resumen(p2)}"
        c.pasa = p1.status_code == 200 and estado == "PAGADO" and p2.status_code == 409

    with rep.caso(
        "Anular un cargo ya pagado",
        "RN-12",
        "409 y el cargo sigue existiendo como PAGADO",
    ) as c:
        if cargo_pagable is None:
            raise RuntimeError("no se creó el cargo del primer caso")
        r = gw.delete("CAJA", f"/api/cargos/{cargo_pagable['id']}")
        sigue = ctx.root.uno("SELECT estado FROM asilo_cobros.cargos WHERE id = %s", (cargo_pagable["id"],))
        c.obtenido = f"{resumen(r)} · en la base: {sigue}"
        c.pasa = r.status_code == 409 and sigue == "PAGADO"

    with rep.caso(
        "Totales del estado de cuenta cuadrados al centavo",
        "CU-12, RN-09, RN-10 y RNF-15",
        "Cuatro cargos (tres de beneficiario, uno sin descuento) y uno de ellos "
        "pagado: cada total coincide al centavo con la suma calculada aparte",
    ) as c:
        cuenta = ctx.cuenta_de_prueba("EC")
        plan = [(t250, 1, True), (t535, 3, True), (t3333, 7, False), (t201, 1, True)]
        creados = []
        for tarifa, cantidad, beneficiario in plan:
            r = ctx.crear_cargo(cuenta, tarifa, cantidad=cantidad, beneficiario=beneficiario)
            if r.status_code != 201:
                raise RuntimeError(f"no se pudo crear un cargo de la cuenta: {resumen(r)}")
            creados.append(r.json())
        pagado = creados[1]
        gw.post("CAJA", f"/api/cargos/{pagado['id']}/pagar")

        esperado = {"bruto": dinero(0), "descuento": dinero(0), "neto": dinero(0)}
        for tarifa, cantidad, beneficiario in plan:
            m = montos_esperados(tarifa["precio"], cantidad, tarifa["descuento_fundacion"], beneficiario)
            for k in esperado:
                esperado[k] += m[k]
        esperado_pagado = montos_esperados(t535["precio"], 3, t535["descuento_fundacion"], True)["neto"]
        esperado_saldo = esperado["neto"] - esperado_pagado

        ec = gw.get("CAJA", f"/api/estado-cuenta/{cuenta}").json()
        comparacion = [
            ("cargos", ec["cantidad_cargos"], 4),
            ("bruto", dinero(ec["total_bruto"]), esperado["bruto"]),
            ("descuento", dinero(ec["total_descuento_fundacion"]), esperado["descuento"]),
            ("neto", dinero(ec["total_neto"]), esperado["neto"]),
            ("pagado", dinero(ec["total_pagado"]), esperado_pagado),
            ("saldo", dinero(ec["saldo_pendiente"]), esperado_saldo),
        ]
        partes = []
        for nombre, real, debe in comparacion:
            if isinstance(debe, int):
                partes.append(f"{nombre} {real}" + ("" if real == debe else f" (se esperaba {debe})"))
            else:
                partes.append(f"{nombre} {q(real)}" + ("" if real == debe else f" (se esperaba {q(debe)})"))
        c.obtenido = " · ".join(partes)
        c.pasa = all(real == debe for _, real, debe in comparacion)
