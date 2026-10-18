"""
S · Reportes

Los siete informes (RF-37 a RF-43). Se arma un caso completo -interno,
remision, visita, ficha, examen con resultado, receta despachada, pago a
la fundacion, donacion y gasto- y se comprueba que cada informe lo
muestra y que sus cifras cuadran al centavo con los registros de los que
sale, leidos aparte por la API de cada modulo.
"""

from apoyo.contexto import dinero, q
from apoyo.gateway import NOMBRE_ROL, TODOS_LOS_ROLES, resumen

LETRA = "S"
TITULO = "Reportes"
DESCRIPCION = (
    "Los siete informes del enunciado: que muestren lo registrado, que sus cifras cuadren "
    "con los módulos de donde salen y que solo los consulte el administrador."
)

A = "ADMIN"


def cifra(informe: dict, etiqueta: str):
    return next((c["valor"] for c in informe.get("resumen", []) if c["etiqueta"] == etiqueta), None)


def seccion(informe: dict, titulo: str) -> dict:
    return next((s for s in informe.get("secciones", []) if s["titulo"] == titulo), {"filas": []})


def ejecutar(ctx) -> None:
    rep, gw = ctx.rep, ctx.gw
    hoy = ctx.hoy.isoformat()
    manana = ctx.hoy.replace(year=ctx.hoy.year + 1).isoformat()

    def informe(clave: str, **params):
        return gw.get(A, f"/api/reportes/{clave}", params=params)

    # ---------------------------------------------------- caso de apoyo
    paciente = ctx.interno("S reportes")
    codigo = paciente["codigo"]
    remision = ctx.remision(paciente, "Cardiología", etiqueta="S reportes")
    r = ctx.convertir(remision["id"], "Cardiología", fecha=f"{hoy} 08:00", medico="Dra. Prueba S")
    if r.status_code != 201:
        raise RuntimeError(f"no se pudo programar la visita de apoyo: {resumen(r)}")
    visita = r.json()["visita"]
    ficha = gw.post("ESPECIALISTA", "/api/fichas", json={
        "visita_id": visita["id"], "diagnostico": f"{ctx.marca} diagnóstico S"}).json()
    examen = next(x for x in gw.get(A, "/api/catalogo/examenes", params={"solo_activos": True}).json() if x["tarifa_id"])
    medicamento = next(x for x in gw.get(A, "/api/catalogo/medicamentos", params={"solo_activos": True}).json() if x["tarifa_id"])
    orden = gw.post("ESPECIALISTA", "/api/examenes", json={"ficha_id": ficha["id"], "tipo_examen_id": examen["id"]}).json()
    gw.post("LABORATORIO", "/api/resultados", json={"orden_id": orden["id"], "resultado": "Resultado S normal"})
    receta = gw.post("ESPECIALISTA", "/api/recetas", json={
        "ficha_id": ficha["id"], "medicamento_id": medicamento["id"], "cantidad": 2,
        "indicaciones": "Una diaria por dos días"}).json()
    gw.post("FARMACIA", "/api/despachos", json={"receta_id": receta["id"], "cantidad": 2})
    cargos = gw.get("CAJA", "/api/cargos", params={"paciente_id": codigo}).json()
    ctx.creados["cargos"].extend(c["id"] for c in cargos)
    por_ref = {c["referencia"]: c for c in cargos}

    with rep.caso(
        "Costos por cita: cuadran con los cargos de la visita",
        "RF-37 · RNF-15",
        "Una fila para la cita; consulta, exámenes, medicamentos, lo que cubrió la fundación "
        "y el total iguales al centavo a los cargos VISITA, EXAMEN y RECETA de esa visita",
    ) as c:
        r = informe("costos", paciente_id=codigo)
        filas = seccion(r.json(), "Detalle por cita")["filas"] if r.status_code == 200 else []
        fila = filas[0] if filas else {}
        esperado = {
            "consulta": dinero(por_ref.get(f"VISITA-{visita['id']}", {}).get("monto_neto")),
            "examenes": dinero(por_ref.get(f"EXAMEN-{orden['id']}", {}).get("monto_neto")),
            "medicamentos": dinero(por_ref.get(f"RECETA-{receta['id']}", {}).get("monto_neto")),
            "fundacion": sum((dinero(x["descuento_aplicado"]) for x in cargos), dinero(0)),
        }
        esperado["total"] = esperado["consulta"] + esperado["examenes"] + esperado["medicamentos"]
        c.obtenido = (
            f"{r.status_code} · filas: {len(filas)}\n"
            + " · ".join(f"{k}: {q(fila.get(k, 0))} (esperado {q(v)})" for k, v in esperado.items())
        )
        c.pasa = (
            r.status_code == 200 and len(filas) == 1 and len(cargos) == 3
            and all(dinero(fila[k]) == v for k, v in esperado.items())
        )

    with rep.caso(
        "Análisis médicos del interno",
        "RF-38",
        "El informe trae el motivo de la remisión, el diagnóstico, el examen con su resultado "
        "y el medicamento; sin interno 422 y con un interno inexistente 404",
    ) as c:
        r = informe("analisis", paciente_id=codigo)
        filas = seccion(r.json(), "Visitas, diagnósticos y tratamiento")["filas"] if r.status_code == 200 else []
        fila = filas[0] if filas else {}
        sin_interno = informe("analisis")
        inexistente = informe("analisis", paciente_id="PAC-NOEXISTE")
        c.obtenido = (
            f"{r.status_code} · visitas: {len(filas)} · motivo: {'sí' if 'remisión de prueba' in fila.get('motivo', '') else 'no'}"
            f" · diagnóstico: {'sí' if 'diagnóstico S' in fila.get('diagnostico', '') else 'no'}"
            f" · resultado: {'sí' if 'Resultado S normal' in fila.get('examenes', '') else 'no'}"
            f" · medicamento: {'sí' if medicamento['nombre'] in fila.get('medicamentos', '') else 'no'}\n"
            f"sin interno: {resumen(sin_interno)}\ninterno inexistente: {resumen(inexistente)}"
        )
        c.pasa = (
            r.status_code == 200 and len(filas) == 1
            and "remisión de prueba" in fila["motivo"] and "diagnóstico S" in fila["diagnostico"]
            and "Resultado S normal" in fila["examenes"] and medicamento["nombre"] in fila["medicamentos"]
            and sin_interno.status_code == 422 and inexistente.status_code == 404
        )

    with rep.caso(
        "Cobros por interno en un rango de fechas",
        "RF-39",
        "Con el rango de hoy salen los tres gastos médicos y su total neto cuadra; con un rango "
        "futuro no sale ninguno; con las fechas al revés 422",
    ) as c:
        r = informe("cobros", paciente_id=codigo, desde=hoy, hasta=hoy)
        detalle = seccion(r.json(), "Gastos médicos") if r.status_code == 200 else {"filas": []}
        futuro = informe("cobros", paciente_id=codigo, desde=manana, hasta=manana)
        al_reves = informe("cobros", paciente_id=codigo, desde=manana, hasta=hoy)
        neto = sum((dinero(x["monto_neto"]) for x in cargos), dinero(0))
        total = dinero((detalle.get("totales") or {}).get("neto"))
        c.obtenido = (
            f"{r.status_code} · gastos médicos: {len(detalle['filas'])} · total neto {q(total)} "
            f"(esperado {q(neto)}) · cargado según el resumen {q(cifra(r.json(), 'Gastos médicos cargados') or 0)}\n"
            f"rango futuro: {len(seccion(futuro.json(), 'Gastos médicos')['filas']) if futuro.status_code == 200 else futuro.status_code} filas"
            f"\nfechas al revés: {resumen(al_reves)}"
        )
        c.pasa = (
            r.status_code == 200 and len(detalle["filas"]) == 3 and total == neto
            and dinero(cifra(r.json(), "Gastos médicos cargados")) == neto
            and futuro.status_code == 200 and not seccion(futuro.json(), "Gastos médicos")["filas"]
            and al_reves.status_code == 422
        )

    pago = gw.post("CAJA", "/api/fundacion/pagos", json={"monto": 12.34, "descripcion": f"{ctx.marca} pago S"})

    with rep.caso(
        "Pagos realizados a la fundación",
        "RF-40",
        "El pago de hoy aparece; lo pagado en el período es la suma de las filas y el saldo es "
        "el mismo que muestra la cuenta con la fundación",
    ) as c:
        r = informe("pagos-fundacion", desde=hoy, hasta=hoy)
        filas = seccion(r.json(), "Pagos")["filas"] if r.status_code == 200 else []
        deuda = gw.get("CAJA", "/api/fundacion/deuda").json()
        suma = sum((dinero(x["monto"]) for x in filas), dinero(0))
        mio = any(f"{ctx.marca} pago S" == x["descripcion"] for x in filas)
        c.obtenido = (
            f"pago de apoyo: {pago.status_code} · {r.status_code} · filas: {len(filas)} · el de hoy: "
            f"{'sí' if mio else 'no'} · pagado en el período {q(cifra(r.json(), 'Pagado en el período') or 0)} "
            f"(suma {q(suma)}) · saldo {q(cifra(r.json(), 'Se le debe hoy') or 0)} (cuenta {q(deuda['saldo'])})"
        )
        c.pasa = (
            pago.status_code == 201 and r.status_code == 200 and mio
            and dinero(cifra(r.json(), "Pagado en el período")) == suma
            and dinero(cifra(r.json(), "Se le debe hoy")) == dinero(deuda["saldo"])
        )

    donacion = gw.post("CAJA", "/api/donaciones", json={
        "origen": f"{ctx.marca} donante S", "tipo_donante": "PARTICULAR", "monto": 250})
    gasto = gw.post("CAJA", "/api/gastos", json={
        "categoria": "AGUA", "monto": 75.5, "descripcion": f"{ctx.marca} gasto S"})
    consulta = por_ref.get(f"VISITA-{visita['id']}") or {}
    pagado = gw.post("CAJA", f"/api/cargos/{consulta.get('id', 0)}/pagar")

    with rep.caso(
        "Ingresos por donaciones y cobros",
        "RF-41",
        "La donación, el cobro pagado hoy y el gasto de hoy aparecen en su sección, y el "
        "balance es donaciones más cobrado menos gastos",
    ) as c:
        r = informe("ingresos", desde=hoy, hasta=hoy)
        j = r.json() if r.status_code == 200 else {}
        donaciones = seccion(j, "Donaciones")["filas"]
        cobrado = seccion(j, "Cobrado a los familiares")["filas"]
        gastos = seccion(j, "Gastos de operación")["filas"]
        aparece = (
            any(x["origen"] == f"{ctx.marca} donante S" for x in donaciones)
            and any(x["interno"].endswith("S reportes") for x in cobrado)
            and any(x["descripcion"] == f"{ctx.marca} gasto S" for x in gastos)
        )
        balance = (sum((dinero(x["monto"]) for x in donaciones), dinero(0))
                   + sum((dinero(x["monto"]) for x in cobrado), dinero(0))
                   - sum((dinero(x["monto"]) for x in gastos), dinero(0)))
        c.obtenido = (
            f"apoyo: donación {donacion.status_code}, gasto {gasto.status_code}, pago del cargo {pagado.status_code} · "
            f"informe {r.status_code} · los tres aparecen: {'sí' if aparece else 'no'}\n"
            f"balance del informe {q(cifra(j, 'Balance') or 0)} · calculado aparte {q(balance)}"
        )
        c.pasa = (
            donacion.status_code == 201 and gasto.status_code == 201 and pagado.status_code == 200
            and r.status_code == 200 and aparece and dinero(cifra(j, "Balance")) == balance
        )

    with rep.caso(
        "Exámenes realizados por interno",
        "RF-42",
        "Sale el examen del interno con su resultado y el laboratorio que lo registró",
    ) as c:
        r = informe("examenes", paciente_id=codigo, desde=hoy, hasta=hoy)
        filas = seccion(r.json(), "Exámenes con resultado")["filas"] if r.status_code == 200 else []
        fila = filas[0] if filas else {}
        c.obtenido = (
            f"{r.status_code} · filas: {len(filas)} · «{fila.get('examen')}» · «{fila.get('resultado')}» · "
            f"{fila.get('laboratorio')}"
        )
        c.pasa = (
            r.status_code == 200 and len(filas) == 1 and fila["examen"] == examen["nombre"]
            and fila["resultado"] == "Resultado S normal" and fila["laboratorio"] == "Lic. Carlos Pérez"
        )

    with rep.caso(
        "Medicamentos aplicados por interno",
        "RF-43",
        "Sale la entrega del interno con la cantidad entregada, cómo se aplica y la farmacia",
    ) as c:
        r = informe("medicamentos", paciente_id=codigo, desde=hoy, hasta=hoy)
        filas = seccion(r.json(), "Medicamentos entregados")["filas"] if r.status_code == 200 else []
        fila = filas[0] if filas else {}
        c.obtenido = (
            f"{r.status_code} · filas: {len(filas)} · «{fila.get('medicamento')}» × {fila.get('cantidad')} · "
            f"«{fila.get('indicaciones')}» · {fila.get('farmacia')}"
        )
        c.pasa = (
            r.status_code == 200 and len(filas) == 1 and fila["cantidad"] == 2
            and fila["indicaciones"] == "Una diaria por dos días" and fila["farmacia"] == "Lic. Sofía Méndez"
        )

    with rep.caso(
        "Solo el administrador consulta los informes",
        "RNF-02 · ACT-05",
        "200 para el administrador y 403 para los otros siete roles; sin sesión 401",
    ) as c:
        codigos = {rol: gw.get(rol, "/api/reportes/ingresos").status_code for rol in TODOS_LOS_ROLES}
        sin_sesion = gw.get(None, "/api/reportes/ingresos").status_code
        c.obtenido = " · ".join(f"{NOMBRE_ROL[k]}: {v}" for k, v in codigos.items()) + f" · sin sesión: {sin_sesion}"
        c.pasa = (
            codigos[A] == 200 and all(v == 403 for k, v in codigos.items() if k != A)
            and sin_sesion == 401
        )
