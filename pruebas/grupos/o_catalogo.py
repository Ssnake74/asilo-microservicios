"""
O · Catalogo medico

Especialidades, medicos y enfermeros salen del catalogo (ms-catalogo), y
la remision y la visita los eligen de ahi. Con el catalogo, RN-05 compara
identificadores y no texto (seccion 17.1 del ERS).

Los datos que se crean llevan la marca en el nombre: el catalogo no tiene
operacion de borrado y la limpieza los encuentra por ella.
"""

from apoyo.gateway import detalle, resumen

LETRA = "O"
TITULO = "Catálogo médico"
DESCRIPCION = (
    "Catálogo sembrado, sus validaciones, y la remisión y la visita eligiendo "
    "especialidad, médico y enfermero del catálogo."
)


def ejecutar(ctx) -> None:
    rep, gw = ctx.rep, ctx.gw
    F = "FUNDACION"

    def crear(lista: str, cuerpo: dict):
        return gw.post(F, f"/api/catalogo/{lista}", json=cuerpo)

    def apoyo(lista: str, cuerpo: dict) -> dict:
        r = crear(lista, cuerpo)
        if r.status_code != 201:
            raise RuntimeError(f"no se pudo crear el registro de apoyo en {lista}: {resumen(r)}")
        return r.json()

    with rep.caso(
        "El catálogo arranca con datos y con precios",
        "RF-27 · sección 17.1 del ERS",
        "Hay especialidades, médicos, enfermeros, exámenes y medicamentos en uso, y "
        "cada examen y medicamento sembrado tiene un concepto del tarifario",
    ) as c:
        conteos, sin_precio = {}, []
        for lista in ("especialidades", "medicos", "enfermeros", "examenes", "medicamentos"):
            registros = gw.get(F, f"/api/catalogo/{lista}", params={"solo_activos": True}).json()
            conteos[lista] = len(registros)
            if lista in ("examenes", "medicamentos"):
                sin_precio += [r["nombre"] for r in registros if r["tarifa_id"] is None]
        c.obtenido = " · ".join(f"{k}: {v}" for k, v in conteos.items()) + (
            f" · sin precio: {', '.join(sin_precio)}" if sin_precio else " · todos con precio"
        )
        c.pasa = all(v > 0 for v in conteos.values()) and not sin_precio

    especialidad = apoyo("especialidades", {"nombre": f"{ctx.marca} O"})
    otra = apoyo("especialidades", {"nombre": f"{ctx.marca} O otra"})
    medico = apoyo("medicos", {"nombre": f"{ctx.marca} Dr. O", "especialidad_id": especialidad["id"]})
    ajeno = apoyo("medicos", {"nombre": f"{ctx.marca} Dr. O ajeno", "especialidad_id": otra["id"]})
    retirado = apoyo("medicos", {"nombre": f"{ctx.marca} Dr. O retirado", "especialidad_id": especialidad["id"]})
    gw.put(F, f"/api/catalogo/medicos/{retirado['id']}", json={"activo": False})
    enfermero = apoyo("enfermeros", {"nombre": f"{ctx.marca} Enf. O"})
    paciente = ctx.interno("O catalogo")

    with rep.caso(
        "Validaciones al agregar al catálogo",
        "Catálogo médico (integridad)",
        "409 para una especialidad que ya existe aunque cambien mayúsculas y espacios, "
        "422 para un médico de una especialidad inexistente y 422 para un nombre en blanco",
    ) as c:
        repetida = crear("especialidades", {"nombre": f"  {ctx.marca.lower()}   o "})
        sin_especialidad = crear("medicos", {"nombre": f"{ctx.marca} Dr. sin", "especialidad_id": 999999999})
        en_blanco = crear("enfermeros", {"nombre": "      "})
        c.obtenido = (
            f"repetida: {resumen(repetida)}\nespecialidad inexistente: {resumen(sin_especialidad)}\n"
            f"en blanco: {resumen(en_blanco)}"
        )
        c.pasa = (
            repetida.status_code == 409
            and sin_especialidad.status_code == 422
            and en_blanco.status_code == 422
        )

    with rep.caso(
        "La remisión guarda la especialidad del catálogo",
        "CU-06 · RF-14",
        "201 con el identificador de la especialidad y su nombre como está en el "
        "catálogo, aunque el texto enviado sea otro",
    ) as c:
        r = ctx.crear_remision(paciente, "texto cualquiera", etiqueta="O remision",
                               especialidad_id=especialidad["id"])
        s = r.json() if r.status_code == 201 else {}
        c.obtenido = resumen(r) if r.status_code != 201 else (
            f"201 · especialidad_id {s['especialidad_id']} · «{s['especialidad_remitida']}»"
        )
        c.pasa = s.get("especialidad_id") == especialidad["id"] and s.get("especialidad_remitida") == especialidad["nombre"]

    with rep.caso(
        "Médico de otra especialidad",
        "RN-05 (por identificador)",
        "422 que nombra la especialidad remitida y la del médico, y la remisión sigue PENDIENTE",
    ) as c:
        remision = ctx.remision(paciente, None, etiqueta="O ajeno", especialidad_id=especialidad["id"])
        r = ctx.programar(remision["id"], medico_id=ajeno["id"], enfermero_id=enfermero["id"])
        estado = gw.get(F, f"/api/solicitudes/{remision['id']}").json()["estado"]
        texto = detalle(r) or ""
        c.obtenido = f"{resumen(r)} · estado: {estado}"
        c.pasa = (
            r.status_code == 422 and especialidad["nombre"] in texto
            and otra["nombre"] in texto and estado == "PENDIENTE"
        )

    with rep.caso(
        "Médico retirado del catálogo",
        "RN-06",
        "422: un médico que ya no atiende no se puede asignar",
    ) as c:
        remision = ctx.remision(paciente, None, etiqueta="O retirado", especialidad_id=especialidad["id"])
        r = ctx.programar(remision["id"], medico_id=retirado["id"], enfermero_id=enfermero["id"])
        c.obtenido = resumen(r)
        c.pasa = r.status_code == 422

    with rep.caso(
        "Enfermero que no está en el catálogo",
        "RF-20",
        "422 y la remisión sigue PENDIENTE",
    ) as c:
        remision = ctx.remision(paciente, None, etiqueta="O enfermero", especialidad_id=especialidad["id"])
        r = ctx.programar(remision["id"], medico_id=medico["id"], enfermero_id=999999999)
        estado = gw.get(F, f"/api/solicitudes/{remision['id']}").json()["estado"]
        c.obtenido = f"{resumen(r)} · estado: {estado}"
        c.pasa = r.status_code == 422 and estado == "PENDIENTE"

    with rep.caso(
        "Visita con médico y enfermero del catálogo",
        "CU-08 · RF-16 · RF-20",
        "201: la visita guarda los identificadores y los nombres del médico, su "
        "especialidad y el enfermero, y el cargo de la consulta queda generado",
    ) as c:
        remision = ctx.remision(paciente, None, etiqueta="O visita", especialidad_id=especialidad["id"])
        r = ctx.programar(remision["id"], medico_id=medico["id"], enfermero_id=enfermero["id"])
        if r.status_code != 201:
            c.obtenido = resumen(r)
        else:
            v = r.json()["visita"]
            c.obtenido = (
                f"201 · visita {v['id']}: médico {v['medico_id']} «{v['medico_tratante']}» "
                f"({v['especialidad']}) · enfermero {v['enfermero_id']} «{v['enfermero']}» · "
                f"cargo_generado={v['cargo_generado']}"
            )
            c.pasa = (
                v["medico_id"] == medico["id"] and v["medico_tratante"] == medico["nombre"]
                and v["especialidad"] == especialidad["nombre"]
                and v["enfermero_id"] == enfermero["id"] and v["enfermero"] == enfermero["nombre"]
                and v["cargo_generado"] is True
            )
