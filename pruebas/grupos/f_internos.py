"""
F · Registro de internos (CU-03)

Las reglas RN-01 a RN-03, el codigo correlativo (RNF-17), la edad que
calcula el sistema y el guardado de tildes y enies (RNF-18).

Todos los internos se crean como la Secretaria, que es quien los registra
en la vida real, y llevan la marca de la corrida en los apellidos.
"""

import re
from datetime import timedelta

from apoyo.contexto import hace_anios
from apoyo.gateway import detalle, resumen

LETRA = "F"
TITULO = "Registro de internos"
DESCRIPCION = "Reglas RN-01 a RN-03, código correlativo, edad calculada y tildes."


def ejecutar(ctx) -> None:
    rep, gw, hoy = ctx.rep, ctx.gw, ctx.hoy
    sesenta = hace_anios(hoy, 60)

    with rep.caso(
        "Interno menor de 60 años (cumple 60 mañana)",
        "RN-01",
        "422 con un mensaje que indica la edad mínima y la edad calculada",
    ) as c:
        nacimiento = sesenta + timedelta(days=1)
        r, _ = ctx.crear_interno("F menor", fecha_nacimiento=nacimiento.isoformat())
        c.obtenido = f"nacimiento {nacimiento} → {resumen(r)}"
        c.pasa = r.status_code == 422 and "60" in (detalle(r) or "")

    with rep.caso(
        "Interno que cumple 60 años exactamente hoy",
        "RN-01 (valor límite)",
        "201, con edad 60",
    ) as c:
        r, _ = ctx.crear_interno("F sesenta", fecha_nacimiento=sesenta.isoformat())
        c.obtenido = f"nacimiento {sesenta} → {resumen(r)}"
        if r.status_code == 201:
            c.obtenido = f"nacimiento {sesenta} → 201 · {r.json()['codigo']} · edad {r.json()['edad']}"
        c.pasa = r.status_code == 201 and r.json().get("edad") == 60

    with rep.caso(
        "Fecha de ingreso anterior a la de nacimiento",
        "RN-02",
        "422 «La fecha de ingreso no puede ser anterior a la fecha de nacimiento.»",
    ) as c:
        r, _ = ctx.crear_interno("F ingreso", fecha_nacimiento="1950-05-20", fecha_ingreso="1950-05-19")
        c.obtenido = f"nacimiento 1950-05-20, ingreso 1950-05-19 → {resumen(r)}"
        c.pasa = r.status_code == 422 and "anterior" in (detalle(r) or "")

    with rep.caso(
        "DPI repetido",
        "RN-03",
        "El primero 201; el segundo con el mismo DPI 409, indicando el código del "
        "interno que ya lo tiene",
    ) as c:
        dpi = "9" + ctx.sello[-12:]
        primero, _ = ctx.crear_interno("F dpi uno", dpi=dpi)
        segundo, _ = ctx.crear_interno("F dpi dos", dpi=dpi)
        codigo = primero.json().get("codigo") if primero.status_code == 201 else None
        c.obtenido = f"DPI {dpi} · primero: {resumen(primero) if not codigo else f'201 · {codigo}'} · segundo: {resumen(segundo)}"
        c.pasa = (
            primero.status_code == 201 and segundo.status_code == 409
            and codigo is not None and codigo in (detalle(segundo) or "")
        )

    sin_dpi = []
    with rep.caso(
        "Alta sin DPI",
        "RN-03 (flujo alterno de CU-03: el DPI es opcional)",
        "Dos altas seguidas sin DPI (null), ambas 201",
    ) as c:
        for n in (1, 2):
            r, _ = ctx.crear_interno(f"F sin dpi {n}", dpi=None)
            sin_dpi.append(r)
        c.obtenido = " · ".join(
            f"alta {i}: {'201 · ' + r.json()['codigo'] if r.status_code == 201 else resumen(r)}"
            for i, r in enumerate(sin_dpi, 1)
        )
        c.pasa = all(r.status_code == 201 for r in sin_dpi)

    with rep.caso(
        "Alta con el DPI vacío («»), como llegaría sin pasar por la interfaz",
        "RN-03 (flujo alterno de CU-03: campo vacío, se omite la validación)",
        "Dos altas seguidas con DPI «», ambas 201",
    ) as c:
        resultados = []
        for n in (1, 2):
            r, _ = ctx.crear_interno(f"F dpi vacio {n}", dpi="")
            resultados.append(r)
        c.obtenido = " · ".join(
            f"alta {i}: {'201 · ' + r.json()['codigo'] if r.status_code == 201 else resumen(r)}"
            for i, r in enumerate(resultados, 1)
        )
        c.pasa = all(r.status_code == 201 for r in resultados)

    with rep.caso(
        "Código correlativo",
        "RNF-17",
        "Formato PAC-NNN, y dos altas consecutivas reciben números consecutivos",
    ) as c:
        codigos = [r.json()["codigo"] for r in sin_dpi if r.status_code == 201]
        if len(codigos) < 2:
            raise RuntimeError("las altas del caso anterior no se crearon")
        formato = all(re.fullmatch(r"PAC-\d{3,}", k) for k in codigos)
        a, b = (int(k.split("-")[1]) for k in codigos)
        c.obtenido = f"{codigos[0]} y luego {codigos[1]}"
        c.pasa = formato and b == a + 1

    with rep.caso(
        "Edad calculada por el sistema",
        "CU-03 (la edad no se escribe, se calcula)",
        "Quien cumple 70 mañana tiene 69; quien cumple 70 hoy tiene 70",
    ) as c:
        manana = hace_anios(hoy + timedelta(days=1), 70)
        cumple_hoy = hace_anios(hoy, 70)
        r1, _ = ctx.crear_interno("F edad 69", fecha_nacimiento=manana.isoformat())
        r2, _ = ctx.crear_interno("F edad 70", fecha_nacimiento=cumple_hoy.isoformat())
        e1 = r1.json().get("edad") if r1.status_code == 201 else resumen(r1)
        e2 = r2.json().get("edad") if r2.status_code == 201 else resumen(r2)
        c.obtenido = f"nacido el {manana}: edad {e1} · nacido el {cumple_hoy}: edad {e2}"
        c.pasa = e1 == 69 and e2 == 70

    with rep.caso(
        "Tildes y eñes guardadas correctamente",
        "RNF-18",
        "Los textos con á, é, í, ó, ú, ñ y ü vuelven idénticos por la API y están "
        "idénticos en la tabla de MySQL",
    ) as c:
        textos = {
            "nombres": "José Ñoño",
            "familiar_nombre": "Begoña Álvarez Güemes",
            "padecimientos": "Hipertensión, artritis y pérdida de audición",
            "procedencia": "Cuyotenango, Suchitepéquez",
        }
        r, ficha = ctx.crear_interno("F Muñoz Pérez", **textos)
        if r.status_code != 201:
            c.obtenido = resumen(r)
        else:
            codigo = r.json()["codigo"]
            api = gw.get("SECRETARIA", f"/api/pacientes/{codigo}").json()
            fila = ctx.root.consulta(
                """SELECT nombres, apellidos, familiar_nombre, padecimientos, procedencia
                   FROM asilo_pacientes.pacientes WHERE codigo = %s""",
                (codigo,),
            )[0]
            campos = list(textos) + ["apellidos"]
            mal = [k for k in campos if api.get(k) != ficha[k] or fila.get(k) != ficha[k]]
            c.obtenido = (
                f"{codigo} · API: «{api['nombres']}», «{api['familiar_nombre']}» · "
                f"MySQL: «{fila['nombres']}», «{fila['apellidos'].split(' ', 2)[-1]}», "
                f"«{fila['padecimientos']}»"
            )
            if mal:
                c.obtenido += f" · campos alterados: {', '.join(mal)}"
            c.pasa = not mal
