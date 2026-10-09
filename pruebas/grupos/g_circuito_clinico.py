"""
G · Circuito clinico (CU-06 y CU-08)

El recorrido completo interno → remision → visita → cargo, y las reglas
RN-04 a RN-08 sobre la conversion de una remision en visita.

Cada caso usa su propia remision: si una regla falla y deja una remision
en un estado inesperado, no arrastra a los casos siguientes.

Las remisiones de este grupo van SIN correo del familiar a proposito.
El aviso por correo se prueba en el grupo L; aqui solo meteria mensajes
de prueba en la bandeja.
"""

from apoyo.contexto import montos_esperados, q
from apoyo.gateway import detalle, resumen

LETRA = "G"
TITULO = "Circuito clínico"
DESCRIPCION = (
    "Interno → remisión → visita → cargo, y las reglas RN-04 a RN-08 al programar "
    "la visita."
)


def ejecutar(ctx) -> None:
    rep, gw = ctx.rep, ctx.gw
    paciente = ctx.interno("G circuito")

    flujo = {}
    with rep.caso(
        "Flujo completo: interno → remisión → visita → cargo",
        "CU-03, CU-06, CU-08 y RN-09",
        "Remisión PENDIENTE; al programar la visita la remisión pasa a CONVERTIDA, "
        "la visita queda con cargo_generado verdadero, y Caja ve el cargo con la "
        "referencia de la visita y el monto con el descuento de la fundación",
    ) as c:
        remision = ctx.remision(paciente, "cardiologia", etiqueta="G flujo")
        r = ctx.convertir(remision["id"], "Cardiologia")
        if r.status_code != 201:
            c.obtenido = f"interno {paciente['codigo']} → remisión {remision['id']} → visita: {resumen(r)}"
        else:
            datos = r.json()
            visita, solicitud = datos["visita"], datos["solicitud"]
            flujo.update(remision=remision, visita=visita)
            cargos = gw.get("CAJA", "/api/cargos", params={"paciente_id": paciente["codigo"]}).json()
            cargo = next((k for k in cargos if k["id"] == visita.get("cargo_id")), None)
            if cargo is None:
                c.obtenido = (
                    f"visita {visita['id']} con cargo_generado={visita['cargo_generado']}, "
                    f"pero Caja no encuentra el cargo · {datos['mensaje_cobro']}"
                )
            else:
                tarifa = gw.get("CAJA", f"/api/tarifas/{cargo['tarifa_id']}").json()
                esperado = montos_esperados(
                    tarifa["precio"], 1, tarifa["descuento_fundacion"], paciente["cubierto_fundacion"]
                )
                montos_bien = (
                    q(cargo["monto_bruto"]) == q(esperado["bruto"])
                    and q(cargo["monto_neto"]) == q(esperado["neto"])
                )
                c.obtenido = (
                    f"interno {paciente['codigo']} → remisión {remision['id']} "
                    f"({remision['estado']}) → visita {visita['id']} (remisión "
                    f"{solicitud['estado']}, cargo_generado={visita['cargo_generado']}) → "
                    f"cargo {cargo['id']} «{cargo['referencia']}»: {q(cargo['monto_bruto'])} − "
                    f"{q(cargo['descuento_aplicado'])} = {q(cargo['monto_neto'])} "
                    f"(tarifa «{tarifa['concepto']}», {tarifa['descuento_fundacion']:g} %)"
                )
                c.pasa = (
                    remision["estado"] == "PENDIENTE"
                    and solicitud["estado"] == "CONVERTIDA"
                    and visita["cargo_generado"] is True
                    and cargo["referencia"] == f"VISITA-{visita['id']}"
                    and montos_bien
                )

    with rep.caso(
        "Programar visita de una remisión anulada",
        "RN-04",
        "La anulación responde 204 y la conversión posterior 409",
    ) as c:
        remision = ctx.remision(paciente, "Neumologia", etiqueta="G anulada")
        anular = gw.delete("MEDICO_GENERAL", f"/api/solicitudes/{remision['id']}")
        r = ctx.convertir(remision["id"], "Neumologia")
        c.obtenido = f"anular: {anular.status_code} · programar visita: {resumen(r)}"
        c.pasa = anular.status_code == 204 and r.status_code == 409

    with rep.caso(
        "Especialidad distinta a la remitida",
        "RN-05",
        "422 con un mensaje que nombra ambas especialidades, ya normalizadas, aunque "
        "se escriban con mayúsculas y espacios de más",
    ) as c:
        remision = ctx.remision(paciente, "  cardiologia ", etiqueta="G distinta")
        r = ctx.convertir(remision["id"], "  DERMATOLOGIA  ")
        texto = detalle(r) or ""
        c.obtenido = resumen(r)
        c.pasa = r.status_code == 422 and "Cardiologia" in texto and "Dermatologia" in texto

    with rep.caso(
        "Misma especialidad con otras mayúsculas y espacios alrededor",
        "RN-05 (normalización)",
        "201: «  nEUROLOGIA  » coincide con la remitida «Neurologia»",
    ) as c:
        remision = ctx.remision(paciente, "Neurologia", etiqueta="G mayusculas")
        r = ctx.convertir(remision["id"], "  nEUROLOGIA  ")
        c.obtenido = resumen(r) if r.status_code != 201 else (
            f"201 · visita {r.json()['visita']['id']} con especialidad "
            f"«{r.json()['visita']['especialidad']}»"
        )
        c.pasa = r.status_code == 201

    with rep.caso(
        "Misma especialidad con espacios de más entre las palabras",
        "RN-05 (normalización)",
        "201: «medicina   interna» coincide con la remitida «Medicina Interna»",
    ) as c:
        remision = ctx.remision(paciente, "Medicina Interna", etiqueta="G espacios")
        r = ctx.convertir(remision["id"], "medicina   interna")
        c.obtenido = resumen(r) if r.status_code != 201 else "201"
        c.pasa = r.status_code == 201

    with rep.caso(
        "Visita sin médico tratante",
        "RN-06",
        "422 tanto con el campo vacío como con solo espacios, y la remisión sigue "
        "PENDIENTE",
    ) as c:
        remision = ctx.remision(paciente, "Oftalmologia", etiqueta="G sin medico")
        vacio = ctx.convertir(remision["id"], "Oftalmologia", medico="")
        espacios = ctx.convertir(remision["id"], "Oftalmologia", medico="     ")
        estado = gw.get("FUNDACION", f"/api/solicitudes/{remision['id']}").json()["estado"]
        c.obtenido = (
            f"vacío: {resumen(vacio)}\nsolo espacios: {resumen(espacios)}\n"
            f"estado de la remisión: {estado}"
        )
        c.pasa = vacio.status_code == 422 and espacios.status_code == 422 and estado == "PENDIENTE"

    with rep.caso(
        "Una remisión no genera dos visitas",
        "RN-07",
        "Programar otra vez la remisión ya convertida responde 409 y sigue habiendo "
        "una sola visita para ella",
    ) as c:
        if not flujo:
            raise RuntimeError("depende del flujo completo, que no llegó a crear la visita")
        r = ctx.convertir(flujo["remision"]["id"], "Cardiologia")
        visitas = ctx.root.uno(
            "SELECT COUNT(*) FROM asilo_solicitudes.visitas WHERE solicitud_id = %s",
            (flujo["remision"]["id"],),
        )
        c.obtenido = f"segunda conversión: {resumen(r)} · visitas de esa remisión: {visitas}"
        c.pasa = r.status_code == 409 and visitas == 1

    with rep.caso(
        "Una remisión convertida no se anula",
        "RN-08",
        "409 y la remisión sigue CONVERTIDA",
    ) as c:
        if not flujo:
            raise RuntimeError("depende del flujo completo, que no llegó a crear la visita")
        r = gw.delete("MEDICO_GENERAL", f"/api/solicitudes/{flujo['remision']['id']}")
        estado = gw.get("FUNDACION", f"/api/solicitudes/{flujo['remision']['id']}").json()["estado"]
        c.obtenido = f"{resumen(r)} · estado: {estado}"
        c.pasa = r.status_code == 409 and estado == "CONVERTIDA"

    with rep.caso(
        "Fecha de la visita con formato inválido",
        "CU-08 (validación de la fecha)",
        "422 con un mensaje que explica el formato AAAA-MM-DD HH:MM",
    ) as c:
        remision = ctx.remision(paciente, "Geriatria", etiqueta="G fecha mala")
        r = ctx.convertir(remision["id"], "Geriatria", fecha="15/12/2026 10:00")
        c.obtenido = resumen(r)
        c.pasa = r.status_code == 422 and "AAAA-MM-DD" in (detalle(r) or "")

    with rep.caso(
        "Formatos de fecha válidos",
        "CU-08 (validación de la fecha)",
        "201 con los formatos que acepta el sistema, guardando la fecha y hora correctas",
    ) as c:
        casos = [
            ("2026-12-01 09:30", "2026-12-01 09:30:00"),
            ("2026-12-01T09:30", "2026-12-01 09:30:00"),
            ("2026-12-01 09:30:15", "2026-12-01 09:30:15"),
            ("2026-12-01", "2026-12-01 00:00:00"),
        ]
        lineas, todos = [], True
        for escrito, guardado in casos:
            remision = ctx.remision(paciente, "Geriatria", etiqueta=f"G fecha {escrito}")
            r = ctx.convertir(remision["id"], "Geriatria", fecha=escrito)
            if r.status_code == 201:
                real = r.json()["visita"]["fecha_visita"]
                lineas.append(f"«{escrito}» → 201, guardada {real}")
                todos &= real == guardado
            else:
                lineas.append(f"«{escrito}» → {resumen(r)}")
                todos = False
        c.obtenido = "\n".join(lineas)
        c.pasa = todos
