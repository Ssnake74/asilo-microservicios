"""
Q · Atencion medica: ficha, laboratorio y farmacia

RF-21 a RF-26 y RF-29: el especialista llena la ficha de la visita,
ordena examenes y receta; el laboratorio registra resultados; la farmacia
despacha; lo hecho y lo entregado se cobra; el historial junta todo.

Los montos del cobro se calculan aqui por separado (montos_esperados),
igual que en el grupo H, para no comparar el sistema consigo mismo.

Las fichas copian el nombre del interno, que lleva la marca: la limpieza
las encuentra por ella.
"""

from apoyo.contexto import dinero, montos_esperados, q
from apoyo.gateway import NOMBRE_ROL, TODOS_LOS_ROLES, detalle, resumen

LETRA = "Q"
TITULO = "Atención médica"
DESCRIPCION = (
    "Ficha de la visita, exámenes y resultados, recetas y despachos, su cobro "
    "automático, el historial del interno y quién puede hacer cada cosa."
)

E, L, F = "ESPECIALISTA", "LABORATORIO", "FARMACIA"
NO_EXISTE = 999999999

# Quien puede cada operacion, escrito a partir del diseño de roles y NO
# importado del gateway: asi la prueba puede fallar.
#   (operacion, metodo, ruta, cuerpo, codigo del servicio si pasa, roles)
PERMISOS = [
    ("Fichas · consultar", "GET", "/api/fichas", None, 200, {"ADMIN", "MEDICO_GENERAL", E}),
    ("Fichas · registrar", "POST", "/api/fichas", {}, 422, {"ADMIN", E}),
    ("Exámenes · consultar", "GET", "/api/examenes", None, 200, {"ADMIN", "MEDICO_GENERAL", E, L}),
    ("Exámenes · ordenar", "POST", "/api/examenes", {}, 422, {"ADMIN", E}),
    ("Resultados · registrar", "POST", "/api/resultados", {}, 422, {"ADMIN", L}),
    ("Recetas · consultar", "GET", "/api/recetas", None, 200, {"ADMIN", "MEDICO_GENERAL", E, F}),
    ("Recetas · recetar", "POST", "/api/recetas", {}, 422, {"ADMIN", E}),
    ("Despachos · registrar", "POST", "/api/despachos", {}, 422, {"ADMIN", F}),
    ("Visitas · consultar", "GET", "/api/visitas", None, 200, {"ADMIN", "SECRETARIA", "MEDICO_GENERAL", "FUNDACION", E}),
]


def ejecutar(ctx) -> None:
    rep, gw = ctx.rep, ctx.gw

    def visita_de_apoyo(etiqueta: str) -> tuple[dict, dict]:
        paciente = ctx.interno(f"Q {etiqueta}")
        solicitud = ctx.remision(paciente, "Cardiología", etiqueta=f"Q {etiqueta}")
        r = ctx.convertir(solicitud["id"], "Cardiología", medico="Dra. Prueba Q")
        if r.status_code != 201:
            raise RuntimeError(f"no se pudo programar la visita de apoyo: {resumen(r)}")
        return paciente, r.json()["visita"]

    def del_catalogo(lista: str) -> dict:
        """Un registro activo del catalogo que ya tenga precio."""
        registros = gw.get(E, f"/api/catalogo/{lista}", params={"solo_activos": True}).json()
        con_precio = [x for x in registros if x.get("tarifa_id")]
        if not con_precio:
            raise RuntimeError(f"el catálogo no tiene {lista} con precio")
        return con_precio[0]

    def tarifa(tarifa_id: int) -> dict:
        return gw.get("CAJA", f"/api/tarifas/{tarifa_id}").json()

    def cargo(cargo_id: int) -> dict | None:
        cargos = gw.get("CAJA", "/api/cargos").json()
        return next((x for x in cargos if x["id"] == cargo_id), None)

    paciente, visita = visita_de_apoyo("principal")
    examen = del_catalogo("examenes")
    medicamento = del_catalogo("medicamentos")

    with rep.caso(
        "El especialista registra la ficha de la visita",
        "RF-21",
        "201 con el diagnóstico, el interno y el médico de la visita, y como responsable "
        "el especialista de la sesión; una segunda ficha para la misma visita 409 y una "
        "visita inexistente 422",
    ) as c:
        r = gw.post(E, "/api/fichas", json={
            "visita_id": visita["id"], "diagnostico": "  Hipertensión arterial grado 1  ",
            "observaciones": "Control en un mes"})
        ficha = r.json() if r.status_code == 201 else {}
        repetida = gw.post(E, "/api/fichas", json={"visita_id": visita["id"], "diagnostico": "Otra cosa"})
        inexistente = gw.post(E, "/api/fichas", json={"visita_id": NO_EXISTE, "diagnostico": "Otra cosa"})
        c.obtenido = (
            f"{r.status_code} · ficha {ficha.get('id')} · «{ficha.get('diagnostico')}» · "
            f"{ficha.get('paciente_id')} · {ficha.get('medico')} · responsable "
            f"{ficha.get('responsable')}\nsegunda ficha: {resumen(repetida)}\n"
            f"visita inexistente: {resumen(inexistente)}"
        )
        c.pasa = (
            r.status_code == 201
            and ficha["diagnostico"] == "Hipertensión arterial grado 1"
            and ficha["paciente_id"] == paciente["codigo"]
            and ficha["medico"] == "Dra. Prueba Q"
            and ficha["responsable"] == "Dra. Ana Sical"
            and repetida.status_code == 409 and inexistente.status_code == 422
        )
    ficha_id = ficha.get("id", NO_EXISTE)

    with rep.caso(
        "El especialista ordena un examen del catálogo",
        "RF-22",
        "201 con la orden pendiente; 422 para un examen que no está en el catálogo y "
        "404 para una ficha que no existe",
    ) as c:
        r = gw.post(E, "/api/examenes", json={
            "ficha_id": ficha_id, "tipo_examen_id": examen["id"], "indicaciones": "En ayunas"})
        orden = r.json() if r.status_code == 201 else {}
        sin_examen = gw.post(E, "/api/examenes", json={"ficha_id": ficha_id, "tipo_examen_id": NO_EXISTE})
        sin_ficha = gw.post(E, "/api/examenes", json={"ficha_id": NO_EXISTE, "tipo_examen_id": examen["id"]})
        c.obtenido = (
            f"{r.status_code} · «{orden.get('examen')}» · {orden.get('estado')}\n"
            f"examen inexistente: {resumen(sin_examen)}\nficha inexistente: {resumen(sin_ficha)}"
        )
        c.pasa = (
            r.status_code == 201 and orden["estado"] == "PENDIENTE" and orden["examen"] == examen["nombre"]
            and sin_examen.status_code == 422 and sin_ficha.status_code == 404
        )
    orden_id = orden.get("id", NO_EXISTE)

    with rep.caso(
        "El laboratorio registra el resultado y el examen se cobra",
        "RF-23 · RF-29 · RN-09",
        "201 con la orden completada y el laboratorio como responsable; se genera el cargo "
        "del examen con el descuento de la fundación; un segundo resultado 409",
    ) as c:
        r = gw.post(L, "/api/resultados", json={"orden_id": orden_id, "resultado": "Glucosa 95 mg/dL, normal"})
        cuerpo = r.json() if r.status_code == 201 else {}
        hecha = cuerpo.get("orden") or {}
        otra = gw.post(L, "/api/resultados", json={"orden_id": orden_id, "resultado": "Otro resultado"})
        cobrado = cargo(hecha["cargo_id"]) if hecha.get("cargo_id") else None
        t = tarifa(examen["tarifa_id"])
        esperado = montos_esperados(t["precio"], 1, t["descuento_fundacion"], True)
        if cobrado:
            ctx.creados["cargos"].append(cobrado["id"])
        c.obtenido = (
            f"{r.status_code} · {hecha.get('estado')} · responsable "
            f"{(hecha.get('resultado') or {}).get('responsable')}\n"
            + (f"cargo {cobrado['id']} «{cobrado['referencia']}»: {q(cobrado['monto_bruto'])} − "
               f"{q(cobrado['descuento_aplicado'])} = {q(cobrado['monto_neto'])} (esperado neto "
               f"{q(esperado['neto'])})" if cobrado else f"sin cargo: {cuerpo.get('mensaje_cobro')}")
            + f"\nsegundo resultado: {resumen(otra)}"
        )
        c.pasa = (
            r.status_code == 201 and hecha["estado"] == "COMPLETADA"
            and hecha["resultado"]["responsable"] == "Lic. Carlos Pérez"
            and cobrado is not None and cobrado["referencia"] == f"EXAMEN-{orden_id}"
            and dinero(cobrado["monto_neto"]) == esperado["neto"]
            and dinero(cobrado["descuento_aplicado"]) == esperado["descuento"]
            and otra.status_code == 409
        )

    with rep.caso(
        "El especialista receta con cantidad y tiempo de aplicación",
        "RF-24",
        "201 con la receta pendiente; 422 para cantidad 0, cantidad 101, indicaciones "
        "de menos de 5 letras y un medicamento que no está en el catálogo",
    ) as c:
        r = gw.post(E, "/api/recetas", json={
            "ficha_id": ficha_id, "medicamento_id": medicamento["id"], "cantidad": 3,
            "indicaciones": "Una tableta cada 12 horas por 10 días"})
        receta = r.json() if r.status_code == 201 else {}
        malos = {
            "cantidad 0": {"cantidad": 0},
            "cantidad 101": {"cantidad": 101},
            "indicaciones cortas": {"indicaciones": "uno"},
            "medicamento inexistente": {"medicamento_id": NO_EXISTE},
        }
        codigos = {}
        for nombre, cambio in malos.items():
            cuerpo = {"ficha_id": ficha_id, "medicamento_id": medicamento["id"], "cantidad": 1,
                      "indicaciones": "Una diaria", **cambio}
            codigos[nombre] = gw.post(E, "/api/recetas", json=cuerpo).status_code
        c.obtenido = (
            f"{r.status_code} · «{receta.get('medicamento')}» × {receta.get('cantidad')} · "
            f"{receta.get('estado')}\n" + " · ".join(f"{k}: {v}" for k, v in codigos.items())
        )
        c.pasa = (
            r.status_code == 201 and receta["estado"] == "PENDIENTE" and receta["cantidad"] == 3
            and all(v == 422 for v in codigos.values())
        )
    receta_id = receta.get("id", NO_EXISTE)

    with rep.caso(
        "La farmacia despacha y se cobra lo entregado",
        "RF-25 · RF-29",
        "422 al intentar entregar más de lo recetado; 201 al entregar 2 de 3, con el cargo "
        "de 2 unidades y el descuento de la fundación; un segundo despacho 409",
    ) as c:
        de_mas = gw.post(F, "/api/despachos", json={"receta_id": receta_id, "cantidad": 4})
        r = gw.post(F, "/api/despachos", json={"receta_id": receta_id, "cantidad": 2})
        cuerpo = r.json() if r.status_code == 201 else {}
        despachada = cuerpo.get("receta") or {}
        despacho = despachada.get("despacho") or {}
        otra = gw.post(F, "/api/despachos", json={"receta_id": receta_id, "cantidad": 1})
        cobrado = cargo(despacho["cargo_id"]) if despacho.get("cargo_id") else None
        t = tarifa(medicamento["tarifa_id"])
        esperado = montos_esperados(t["precio"], 2, t["descuento_fundacion"], True)
        if cobrado:
            ctx.creados["cargos"].append(cobrado["id"])
        c.obtenido = (
            f"más de lo recetado: {resumen(de_mas)}\n{r.status_code} · {despachada.get('estado')} · "
            f"entregadas {despacho.get('cantidad_despachada')} · responsable {despacho.get('responsable')}\n"
            + (f"cargo {cobrado['id']} «{cobrado['referencia']}» × {cobrado['cantidad']}: neto "
               f"{q(cobrado['monto_neto'])} (esperado {q(esperado['neto'])})"
               if cobrado else f"sin cargo: {cuerpo.get('mensaje_cobro')}")
            + f"\nsegundo despacho: {resumen(otra)}"
        )
        c.pasa = (
            de_mas.status_code == 422 and r.status_code == 201
            and despachada["estado"] == "DESPACHADA" and despacho["cantidad_despachada"] == 2
            and despacho["responsable"] == "Lic. Sofía Méndez"
            and cobrado is not None and cobrado["cantidad"] == 2
            and cobrado["referencia"] == f"RECETA-{receta_id}"
            and dinero(cobrado["monto_neto"]) == esperado["neto"]
            and otra.status_code == 409
        )

    with rep.caso(
        "Un examen sin precio en el catálogo se registra sin cobro",
        "RF-29 (examen sin concepto del tarifario)",
        "201 con el resultado guardado, cargo_generado falso y un aviso de que el examen "
        "no tiene precio",
    ) as c:
        nuevo = gw.post("FUNDACION", "/api/catalogo/examenes", json={"nombre": f"{ctx.marca} Q sin precio"})
        if nuevo.status_code != 201:
            raise RuntimeError(f"no se pudo crear el examen de apoyo: {resumen(nuevo)}")
        o = gw.post(E, "/api/examenes", json={"ficha_id": ficha_id, "tipo_examen_id": nuevo.json()["id"]}).json()
        r = gw.post(L, "/api/resultados", json={"orden_id": o["id"], "resultado": "Sin hallazgos"})
        cuerpo = r.json() if r.status_code == 201 else {}
        c.obtenido = (
            f"{r.status_code} · cargo_generado={(cuerpo.get('orden') or {}).get('cargo_generado')} · "
            f"«{cuerpo.get('mensaje_cobro')}»"
        )
        c.pasa = (
            r.status_code == 201 and cuerpo["orden"]["cargo_generado"] is False
            and "no tiene precio" in cuerpo["mensaje_cobro"]
        )

    with rep.caso(
        "El responsable lo pone el gateway, no el navegador",
        "RNF-02 (la identidad sale solo de la sesión)",
        "Un resultado enviado con el encabezado «X-Usuario: Otra persona» queda a nombre "
        "del usuario de la sesión",
    ) as c:
        o = gw.post(E, "/api/examenes", json={"ficha_id": ficha_id, "tipo_examen_id": examen["id"]}).json()
        r = gw.pedir("POST", "/api/resultados", gw.como(L),
                     json={"orden_id": o["id"], "resultado": "Prueba de suplantación"},
                     headers={"X-Usuario": "Otra persona"})
        cuerpo = r.json() if r.status_code == 201 else {}
        if (cuerpo.get("orden") or {}).get("cargo_id"):
            ctx.creados["cargos"].append(cuerpo["orden"]["cargo_id"])
        responsable = ((cuerpo.get("orden") or {}).get("resultado") or {}).get("responsable")
        c.obtenido = f"{r.status_code} · responsable: {responsable}"
        c.pasa = r.status_code == 201 and responsable == "Lic. Carlos Pérez"

    with rep.caso(
        "El historial médico junta la ficha con sus exámenes y medicamentos",
        "RF-26",
        "El médico general recibe la ficha del interno con sus tres exámenes, todos con "
        "resultado, y la receta con su despacho; secretaria, fundación y caja 403",
    ) as c:
        r = gw.get("MEDICO_GENERAL", "/api/fichas", params={"paciente_id": paciente["codigo"]})
        fichas = r.json() if r.status_code == 200 else []
        f = fichas[0] if fichas else {}
        examenes = f.get("examenes", [])
        recetas = f.get("recetas", [])
        negados = {rol: gw.get(rol, "/api/fichas", params={"paciente_id": paciente["codigo"]}).status_code
                   for rol in ("SECRETARIA", "FUNDACION", "CAJA")}
        c.obtenido = (
            f"{r.status_code} · fichas: {len(fichas)} · exámenes: {len(examenes)} "
            f"(con resultado: {sum(1 for o in examenes if o['resultado'])}) · recetas: {len(recetas)} "
            f"(despachadas: {sum(1 for x in recetas if x['despacho'])})\n"
            + " · ".join(f"{NOMBRE_ROL[k]}: {v}" for k, v in negados.items())
        )
        c.pasa = (
            r.status_code == 200 and len(fichas) == 1 and len(examenes) == 3
            and all(o["resultado"] for o in examenes)
            and len(recetas) == 1 and recetas[0]["despacho"] is not None
            and all(v == 403 for v in negados.values())
        )

    with rep.caso(
        "Quién puede cada operación de la atención médica",
        "RNF-02 · RF-03",
        "Cada operación responde el servicio para los roles con permiso y 403 del gateway "
        "para los demás, en los ocho roles",
    ) as c:
        lineas, todo_bien = [], True
        for operacion, metodo, ruta, cuerpo, codigo, permitidos in PERMISOS:
            malos = []
            for rol in TODOS_LOS_ROLES:
                r = gw.pedir(metodo, ruta, gw.como(rol), json=cuerpo,
                             params={"paciente_id": "NOEXISTE"} if metodo == "GET" else None)
                bien = (r.status_code == codigo and detalle(r) != "Ese recurso no existe en el sistema."
                        if rol in permitidos else r.status_code == 403)
                if not bien:
                    malos.append(f"{NOMBRE_ROL[rol]} {r.status_code}")
            todo_bien &= not malos
            lineas.append(f"{operacion}: " + ("bien" if not malos else "MAL " + ", ".join(malos)))
        c.obtenido = "\n".join(lineas)
        c.pasa = todo_bien
