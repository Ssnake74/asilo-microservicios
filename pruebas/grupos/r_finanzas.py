"""
R · Entradas, salidas y egreso

RF-33 a RF-36: cuotas mensuales, donaciones, gastos y la cuenta con la
fundacion. RF-13: el egreso o fallecimiento de un interno sin perder su
historial.

Todo lo que se crea lleva la marca (en el origen, la descripcion o el
nombre del interno) y la limpieza lo borra como root: estos registros no
tienen operacion de borrado.
"""

from apoyo.contexto import dinero, montos_esperados, q
from apoyo.gateway import NOMBRE_ROL, TODOS_LOS_ROLES, detalle, resumen

LETRA = "R"
TITULO = "Entradas, salidas y egreso"
DESCRIPCION = (
    "Cuotas mensuales, donaciones, gastos, la deuda y los pagos a la fundación, y el "
    "egreso o fallecimiento de un interno conservando su historial."
)

C = "CAJA"

# Quien puede cada operacion, escrito a partir del diseño de roles y NO
# importado del gateway. (operacion, metodo, ruta, cuerpo, codigo si pasa, roles)
PERMISOS = [
    ("Cuotas · consultar", "GET", "/api/cuotas", None, 200, {"ADMIN", "SECRETARIA", C}),
    ("Cuotas · registrar", "POST", "/api/cuotas", {}, 422, {"ADMIN", C}),
    ("Donaciones · consultar", "GET", "/api/donaciones", None, 200, {"ADMIN", C}),
    ("Donaciones · registrar", "POST", "/api/donaciones", {}, 422, {"ADMIN", C}),
    ("Gastos · consultar", "GET", "/api/gastos", None, 200, {"ADMIN", C}),
    ("Gastos · registrar", "POST", "/api/gastos", {}, 422, {"ADMIN", C}),
    ("Fundación · consultar la deuda", "GET", "/api/fundacion/deuda", None, 200, {"ADMIN", C, "FUNDACION"}),
    ("Fundación · registrar un pago", "POST", "/api/fundacion/pagos", {}, 422, {"ADMIN", C}),
]


def ejecutar(ctx) -> None:
    rep, gw = ctx.rep, ctx.gw
    hoy = ctx.hoy.isoformat()
    manana = ctx.hoy.replace(year=ctx.hoy.year + 1).isoformat()

    with rep.caso(
        "Donación registrada y sus validaciones",
        "RF-34",
        "201 con el origen sin espacios de más, la fecha de hoy y el monto exacto; 422 "
        "para un tipo de donante que no existe, un monto de cero y una fecha futura",
    ) as c:
        r = gw.post(C, "/api/donaciones", json={
            "origen": f"  {ctx.marca}   Rotary  ", "tipo_donante": "EMPRESA_NACIONAL", "monto": 2500.55})
        d = r.json() if r.status_code == 201 else {}
        malos = {
            "tipo inexistente": {"tipo_donante": "VECINO"},
            "monto cero": {"monto": 0},
            "fecha futura": {"fecha": manana},
        }
        codigos = {}
        for nombre, cambio in malos.items():
            cuerpo = {"origen": f"{ctx.marca} malo", "tipo_donante": "PARTICULAR", "monto": 10, **cambio}
            codigos[nombre] = resumen(gw.post(C, "/api/donaciones", json=cuerpo))
        c.obtenido = (
            f"{r.status_code} · «{d.get('origen')}» · {d.get('fecha')} · {q(d.get('monto', 0))}\n"
            + "\n".join(f"{k}: {v}" for k, v in codigos.items())
        )
        c.pasa = (
            r.status_code == 201 and d["origen"] == f"{ctx.marca} Rotary"
            and d["fecha"] == hoy and dinero(d["monto"]) == dinero("2500.55")
            and all(v.startswith("422") for v in codigos.values())
        )

    with rep.caso(
        "Gasto registrado y sus validaciones",
        "RF-35",
        "201 con la categoría, la descripción y el comprobante; 422 para una categoría "
        "que no existe y para un gasto sin descripción",
    ) as c:
        r = gw.post(C, "/api/gastos", json={
            "categoria": "LUZ", "monto": 845.30, "descripcion": f"{ctx.marca} recibo de luz",
            "comprobante": "Serie A 001"})
        g = r.json() if r.status_code == 201 else {}
        sin_categoria = gw.post(C, "/api/gastos", json={
            "categoria": "FIESTAS", "monto": 5, "descripcion": f"{ctx.marca} x"})
        sin_descripcion = gw.post(C, "/api/gastos", json={"categoria": "AGUA", "monto": 5, "descripcion": "   "})
        c.obtenido = (
            f"{r.status_code} · {g.get('categoria')} · {q(g.get('monto', 0))} · {g.get('comprobante')}\n"
            f"categoría inexistente: {resumen(sin_categoria)}\nsin descripción: {resumen(sin_descripcion)}"
        )
        c.pasa = (
            r.status_code == 201 and g["categoria"] == "LUZ" and dinero(g["monto"]) == dinero("845.30")
            and sin_categoria.status_code == 422 and sin_descripcion.status_code == 422
        )

    uno = ctx.interno("R cuota uno")
    dos = ctx.interno("R cuota dos")
    internos = [{"paciente_id": p["codigo"], "paciente_nombre": f"{p['nombres']} {p['apellidos']}"}
                for p in (uno, dos)]
    periodo = "2099-01"

    with rep.caso(
        "Cuotas del mes, una por interno",
        "RF-33",
        "Generar las cuotas de un mes para dos internos crea 2; generarlas otra vez crea 0 "
        "y dice que 2 ya existían; un mes mal escrito 422",
    ) as c:
        primera = gw.post(C, "/api/cuotas/generar", json={"periodo": periodo, "monto": 1500, "internos": internos})
        segunda = gw.post(C, "/api/cuotas/generar", json={"periodo": periodo, "monto": 1500, "internos": internos})
        mal_mes = gw.post(C, "/api/cuotas/generar", json={"periodo": "2099-13", "monto": 1500, "internos": internos})
        p, s = primera.json(), segunda.json()
        c.obtenido = (
            f"primera: {primera.status_code}, creadas {p.get('creadas')} · segunda: creadas "
            f"{s.get('creadas')}, ya existían {s.get('ya_existian')}\nmes mal escrito: {resumen(mal_mes)}"
        )
        c.pasa = (
            primera.status_code == 201 and p["creadas"] == 2
            and s["creadas"] == 0 and s["ya_existian"] == 2 and mal_mes.status_code == 422
        )

    with rep.caso(
        "Pago y anulación de una cuota",
        "RF-33 (una cuota no se cobra dos veces)",
        "Pagar responde 200 con la cuota PAGADA; pagarla otra vez 409; anular una pagada "
        "409; anular una pendiente 204",
    ) as c:
        cuotas = gw.get(C, "/api/cuotas", params={"periodo": periodo}).json()
        mias = [x for x in cuotas if x["paciente_id"] in (uno["codigo"], dos["codigo"])]
        if len(mias) != 2:
            raise RuntimeError(f"se esperaban 2 cuotas de prueba y hay {len(mias)}")
        pagar = gw.post(C, f"/api/cuotas/{mias[0]['id']}/pagar")
        otra = gw.post(C, f"/api/cuotas/{mias[0]['id']}/pagar")
        anular_pagada = gw.delete(C, f"/api/cuotas/{mias[0]['id']}")
        anular_pendiente = gw.delete(C, f"/api/cuotas/{mias[1]['id']}")
        c.obtenido = (
            f"pagar: {pagar.status_code} · {pagar.json().get('estado')} · otra vez: {resumen(otra)}\n"
            f"anular la pagada: {resumen(anular_pagada)} · anular la pendiente: {anular_pendiente.status_code}"
        )
        c.pasa = (
            pagar.status_code == 200 and pagar.json()["estado"] == "PAGADA"
            and otra.status_code == 409 and anular_pagada.status_code == 409
            and anular_pendiente.status_code == 204
        )

    with rep.caso(
        "Deuda con la fundación y pagos a ella",
        "RF-36 · RNF-15",
        "Un cargo nuevo sube la deuda exactamente en su neto; un pago la baja exactamente "
        "en su monto; un pago mayor que lo que se debe 422",
    ) as c:
        antes = gw.get(C, "/api/fundacion/deuda").json()
        tarifa = ctx.tarifa("R deuda", "EXAMEN", 333.33, 40)
        cargo = ctx.crear_cargo(ctx.cuenta_de_prueba("R"), tarifa, cantidad=3)
        if cargo.status_code != 201:
            raise RuntimeError(f"no se pudo crear el cargo de apoyo: {resumen(cargo)}")
        neto = montos_esperados(333.33, 3, 40, True)["neto"]
        con_cargo = gw.get(C, "/api/fundacion/deuda").json()
        pago = gw.post(C, "/api/fundacion/pagos", json={"monto": 123.45, "descripcion": f"{ctx.marca} abono"})
        con_pago = gw.get(C, "/api/fundacion/deuda").json()
        de_mas = gw.post(C, "/api/fundacion/pagos", json={
            "monto": float(dinero(con_pago["saldo"]) + dinero("0.01")), "descripcion": f"{ctx.marca} de mas"})
        subio = dinero(con_cargo["saldo"]) - dinero(antes["saldo"])
        bajo = dinero(con_cargo["saldo"]) - dinero(con_pago["saldo"])
        c.obtenido = (
            f"saldo antes {q(antes['saldo'])} · con el cargo {q(con_cargo['saldo'])} (subió {q(subio)}, "
            f"neto esperado {q(neto)}) · con el pago {q(con_pago['saldo'])} (bajó {q(bajo)})\n"
            f"pago mayor que la deuda: {resumen(de_mas)}"
        )
        c.pasa = (
            subio == neto and pago.status_code == 201 and bajo == dinero("123.45")
            and de_mas.status_code == 422
        )

    with rep.caso(
        "Egreso de un interno y su reingreso",
        "RF-13",
        "EGRESADO responde 200 con la fecha de hoy y el motivo; una fecha anterior al "
        "ingreso o futura 422; volver a ACTIVO borra la fecha y el motivo",
    ) as c:
        p = ctx.interno("R egreso")
        ruta = f"/api/pacientes/{p['codigo']}"
        anterior = gw.put("SECRETARIA", ruta, json={"estado": "EGRESADO", "fecha_egreso": "1950-01-01"})
        futura = gw.put("SECRETARIA", ruta, json={"estado": "EGRESADO", "fecha_egreso": manana})
        egreso = gw.put("SECRETARIA", ruta, json={"estado": "EGRESADO", "motivo_egreso": "Traslado con su familia"})
        e = egreso.json() if egreso.status_code == 200 else {}
        reingreso = gw.put("SECRETARIA", ruta, json={"estado": "ACTIVO"})
        r = reingreso.json() if reingreso.status_code == 200 else {}
        c.obtenido = (
            f"anterior al ingreso: {resumen(anterior)}\nfutura: {resumen(futura)}\n"
            f"egreso: {egreso.status_code} · {e.get('estado')} · {e.get('fecha_egreso')} · «{e.get('motivo_egreso')}»\n"
            f"reingreso: {reingreso.status_code} · {r.get('estado')} · fecha {r.get('fecha_egreso')}"
        )
        c.pasa = (
            anterior.status_code == 422 and futura.status_code == 422
            and egreso.status_code == 200 and e["estado"] == "EGRESADO" and e["fecha_egreso"] == hoy
            and e["motivo_egreso"] == "Traslado con su familia"
            and reingreso.status_code == 200 and r["estado"] == "ACTIVO" and r["fecha_egreso"] is None
        )

    with rep.caso(
        "El fallecimiento conserva el historial",
        "RF-13",
        "Un interno con una visita pasa a FALLECIDO; su ficha, su remisión y su visita "
        "siguen consultándose",
    ) as c:
        p = ctx.interno("R fallecido")
        solicitud = ctx.remision(p, "Geriatría", etiqueta="R fallecido")
        visita = ctx.convertir(solicitud["id"], "Geriatría")
        r = gw.put("SECRETARIA", f"/api/pacientes/{p['codigo']}", json={
            "estado": "FALLECIDO", "motivo_egreso": "Causas naturales"})
        ficha = gw.get("SECRETARIA", f"/api/pacientes/{p['codigo']}")
        remisiones = gw.get("FUNDACION", "/api/solicitudes", params={"paciente_id": p["codigo"]}).json()
        visitas = gw.get("FUNDACION", "/api/visitas", params={"paciente_id": p["codigo"]}).json()
        c.obtenido = (
            f"visita: {visita.status_code} · fallecimiento: {r.status_code} · ficha: {ficha.status_code} "
            f"({ficha.json().get('estado')}) · remisiones: {len(remisiones)} · visitas: {len(visitas)}"
        )
        c.pasa = (
            visita.status_code == 201 and r.status_code == 200
            and ficha.status_code == 200 and ficha.json()["estado"] == "FALLECIDO"
            and len(remisiones) == 1 and len(visitas) == 1
        )

    with rep.caso(
        "Quién puede cada operación de entradas y salidas",
        "RNF-02 · RF-03",
        "Cada operación responde el servicio para los roles con permiso y 403 del gateway "
        "para los demás, en los ocho roles",
    ) as c:
        lineas, todo_bien = [], True
        for operacion, metodo, ruta, cuerpo, codigo, permitidos in PERMISOS:
            malos = []
            for rol in TODOS_LOS_ROLES:
                r = gw.pedir(metodo, ruta, gw.como(rol), json=cuerpo,
                             params={"periodo": "2099-02"} if ruta == "/api/cuotas" and metodo == "GET" else None)
                bien = (r.status_code == codigo and detalle(r) != "Ese recurso no existe en el sistema."
                        if rol in permitidos else r.status_code == 403)
                if not bien:
                    malos.append(f"{NOMBRE_ROL[rol]} {r.status_code}")
            todo_bien &= not malos
            lineas.append(f"{operacion}: " + ("bien" if not malos else "MAL " + ", ".join(malos)))
        c.obtenido = "\n".join(lineas)
        c.pasa = todo_bien
