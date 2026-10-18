"""
Reglas de armado de los siete informes (RF-37 a RF-43).

Funciones puras: reciben lo que devolvieron los otros servicios y
devuelven el informe. No hacen HTTP ni saben de FastAPI, asi que se
pueden probar con datos fijos.

Las sumas de dinero van en Decimal (RNF-15) y se pasan a float solo al
final, para el JSON.
"""

from collections import Counter, defaultdict
from decimal import ROUND_HALF_UP, Decimal

CENTAVOS = Decimal("0.01")

NOMBRE_TIPO_CARGO = {"CITA": "Consulta", "EXAMEN": "Examen", "MEDICAMENTO": "Medicamento"}
NOMBRE_DONANTE = {
    "EMPRESA_INTERNACIONAL": "Empresa internacional", "EMPRESA_NACIONAL": "Empresa nacional",
    "GOBIERNO": "Gobierno", "PARTICULAR": "Persona particular",
}
NOMBRE_ESTADO = {"PENDIENTE": "Por cobrar", "PAGADO": "Pagado", "PAGADA": "Pagada"}


# ------------------------------------------------------------- ayudas

def dinero(valor) -> Decimal:
    return Decimal(str(valor or 0)).quantize(CENTAVOS, rounding=ROUND_HALF_UP)


def sumar(filas: list[dict], campo: str) -> Decimal:
    return sum((dinero(f.get(campo)) for f in filas), Decimal("0.00"))


def a_float(valor: Decimal) -> float:
    return float(valor.quantize(CENTAVOS, rounding=ROUND_HALF_UP))


def dia(fecha: str | None) -> str:
    """Los primeros 10 caracteres: AAAA-MM-DD, sin la hora."""
    return (fecha or "")[:10]


def en_rango(fecha: str | None, desde: str | None, hasta: str | None) -> bool:
    d = dia(fecha)
    if not d:
        return False
    return (not desde or d >= desde) and (not hasta or d <= hasta)


def columna(clave: str, titulo: str, tipo: str = "texto") -> dict:
    return {"clave": clave, "titulo": titulo, "tipo": tipo}


def cifra(etiqueta: str, valor, tipo: str = "dinero") -> dict:
    return {"etiqueta": etiqueta, "valor": a_float(valor) if isinstance(valor, Decimal) else valor, "tipo": tipo}


def nombre_interno(internos: dict, codigo: str, respaldo: str = "") -> str:
    p = internos.get(codigo)
    return f"{p['nombres']} {p['apellidos']}" if p else (respaldo or codigo)


def cargos_por_referencia(cargos: list[dict]) -> dict[str, list[dict]]:
    """Los cargos agrupados por su referencia: VISITA-7, EXAMEN-3, RECETA-5."""
    grupos = defaultdict(list)
    for c in cargos:
        if c.get("referencia"):
            grupos[c["referencia"]].append(c)
    return grupos


# ------------------------------------------- RF-37 · costos por cita

def costos_por_cita(visitas: list[dict], fichas: list[dict], cargos: list[dict],
                    internos: dict, desde: str | None, hasta: str | None) -> dict:
    """
    Una fila por visita: lo que costo la consulta, sus examenes y sus
    medicamentos. Los examenes y medicamentos se ligan a la visita por la
    ficha medica; sus cargos, por la referencia que les puso ms-clinico.
    """
    por_ref = cargos_por_referencia(cargos)
    ficha_de = {f["visita_id"]: f for f in fichas}
    filas = []
    for v in sorted(visitas, key=lambda x: x["fecha_visita"]):
        if not en_rango(v["fecha_visita"], desde, hasta):
            continue
        ficha = ficha_de.get(v["id"])
        consulta = por_ref.get(f"VISITA-{v['id']}", [])
        examenes = [c for o in (ficha or {}).get("examenes", []) for c in por_ref.get(f"EXAMEN-{o['id']}", [])]
        medicinas = [c for r in (ficha or {}).get("recetas", []) for c in por_ref.get(f"RECETA-{r['id']}", [])]
        todos = consulta + examenes + medicinas
        filas.append({
            "fecha": v["fecha_visita"],
            "interno": nombre_interno(internos, v["paciente_id"], v["paciente_nombre"]),
            "especialidad": f"{v['especialidad']} · {v['medico_tratante']}",
            "consulta": a_float(sumar(consulta, "monto_neto")),
            "examenes": a_float(sumar(examenes, "monto_neto")),
            "medicamentos": a_float(sumar(medicinas, "monto_neto")),
            "fundacion": a_float(sumar(todos, "descuento_aplicado")),
            "total": a_float(sumar(todos, "monto_neto")),
        })
    claves = ("consulta", "examenes", "medicamentos", "fundacion", "total")
    totales = {k: a_float(sumar(filas, k)) for k in claves}
    return {
        "titulo": "Costos por cita y por interno",
        "requisito": "RF-37",
        "resumen": [
            cifra("Citas", len(filas), "numero"),
            cifra("Consultas", dinero(totales["consulta"])),
            cifra("Exámenes", dinero(totales["examenes"])),
            cifra("Medicamentos", dinero(totales["medicamentos"])),
            cifra("Cubierto por la fundación", dinero(totales["fundacion"])),
            cifra("Total a cargo del familiar", dinero(totales["total"])),
        ],
        "secciones": [{
            "titulo": "Detalle por cita",
            "columnas": [
                columna("fecha", "Fecha", "fecha"), columna("interno", "Interno"),
                columna("especialidad", "Especialidad y médico"),
                columna("consulta", "Consulta", "dinero"), columna("examenes", "Exámenes", "dinero"),
                columna("medicamentos", "Medicamentos", "dinero"),
                columna("fundacion", "Cubrió la fundación", "dinero"), columna("total", "Total", "dinero"),
            ],
            "filas": filas,
            "totales": totales,
            "vacio": "No hay citas en esas fechas.",
        }],
    }


# ----------------------------------- RF-38 · analisis medicos por interno

def analisis_medicos(interno: dict, remisiones: list[dict], visitas: list[dict],
                     fichas: list[dict]) -> dict:
    """La ficha del interno y, por cada visita, por que fue remitido, que se encontro y que se hizo."""
    motivo_de = {s["id"]: s for s in remisiones}
    ficha_de = {f["visita_id"]: f for f in fichas}
    filas = []
    for v in sorted(visitas, key=lambda x: x["fecha_visita"], reverse=True):
        ficha = ficha_de.get(v["id"])
        remision = motivo_de.get(v["solicitud_id"], {})
        examenes = "; ".join(
            f"{o['examen']}: {o['resultado']['resultado']}" if o.get("resultado") else f"{o['examen']}: sin resultado"
            for o in (ficha or {}).get("examenes", [])
        )
        medicinas = "; ".join(
            f"{r['medicamento']} × {r['cantidad']}, {r['indicaciones']}"
            for r in (ficha or {}).get("recetas", [])
        )
        filas.append({
            "fecha": v["fecha_visita"],
            "especialidad": f"{v['especialidad']} · {v['medico_tratante']}",
            "motivo": remision.get("motivo", ""),
            "diagnostico": ficha["diagnostico"] if ficha else "Sin ficha médica todavía",
            "examenes": examenes or "—",
            "medicamentos": medicinas or "—",
        })
    return {
        "titulo": f"Análisis médicos de {interno['nombres']} {interno['apellidos']}",
        "requisito": "RF-38",
        "resumen": [
            cifra("Código", interno["codigo"], "texto"),
            cifra("Edad", f"{interno['edad']} años", "texto"),
            cifra("Estado", interno["estado"].capitalize(), "texto"),
            cifra("Padecimientos", interno.get("padecimientos") or "Ninguno anotado", "texto"),
            cifra("Alergias", interno.get("alergias") or "Ninguna anotada", "texto"),
            cifra("Visitas médicas", len(filas), "numero"),
        ],
        "secciones": [{
            "titulo": "Visitas, diagnósticos y tratamiento",
            "columnas": [
                columna("fecha", "Fecha", "fecha"), columna("especialidad", "Especialidad y médico"),
                columna("motivo", "Por qué fue remitido"), columna("diagnostico", "Diagnóstico"),
                columna("examenes", "Exámenes y resultados"), columna("medicamentos", "Medicamentos"),
            ],
            "filas": filas,
            "vacio": "Este interno todavía no tiene visitas médicas.",
        }],
    }


# ------------------------------------- RF-39 · cobros por interno y fechas

def cobros_por_interno(interno: dict, cargos: list[dict], cuotas: list[dict],
                       desde: str | None, hasta: str | None) -> dict:
    """Lo que se le cargo al familiar en el rango, con el detalle de los gastos medicos, y sus cuotas."""
    cargos = sorted((c for c in cargos if en_rango(c["fecha"], desde, hasta)), key=lambda c: c["fecha"])
    mes_desde, mes_hasta = (desde or "")[:7], (hasta or "")[:7]
    cuotas = sorted(
        (c for c in cuotas if (not mes_desde or c["periodo"] >= mes_desde) and (not mes_hasta or c["periodo"] <= mes_hasta)),
        key=lambda c: c["periodo"],
    )
    filas_cargos = [{
        "fecha": c["fecha"], "concepto": c["concepto"], "tipo": NOMBRE_TIPO_CARGO.get(c["tipo"], c["tipo"]),
        "cantidad": c["cantidad"], "bruto": c["monto_bruto"], "descuento": c["descuento_aplicado"],
        "neto": c["monto_neto"], "estado": NOMBRE_ESTADO.get(c["estado"], c["estado"]),
    } for c in cargos]
    filas_cuotas = [{
        "periodo": c["periodo"], "monto": c["monto"], "estado": NOMBRE_ESTADO.get(c["estado"], c["estado"]),
        "fecha_pago": c.get("fecha_pago") or "",
    } for c in cuotas]
    neto = sumar(cargos, "monto_neto")
    pagado = sumar([c for c in cargos if c["estado"] == "PAGADO"], "monto_neto")
    cuotas_total = sumar(cuotas, "monto")
    cuotas_pagadas = sumar([c for c in cuotas if c["estado"] == "PAGADA"], "monto")
    return {
        "titulo": f"Cobros de {interno['nombres']} {interno['apellidos']}",
        "requisito": "RF-39",
        "resumen": [
            cifra("Gastos médicos cargados", neto),
            cifra("Cubierto por la fundación", sumar(cargos, "descuento_aplicado")),
            cifra("Gastos médicos pagados", pagado),
            cifra("Cuotas del período", cuotas_total),
            cifra("Cuotas pagadas", cuotas_pagadas),
            cifra("Saldo pendiente", (neto - pagado) + (cuotas_total - cuotas_pagadas)),
        ],
        "secciones": [
            {
                "titulo": "Gastos médicos",
                "columnas": [
                    columna("fecha", "Fecha", "fecha"), columna("concepto", "Concepto"), columna("tipo", "Tipo"),
                    columna("cantidad", "Cantidad", "numero"), columna("bruto", "Precio", "dinero"),
                    columna("descuento", "Fundación", "dinero"), columna("neto", "A pagar", "dinero"),
                    columna("estado", "Estado"),
                ],
                "filas": filas_cargos,
                "totales": {k: a_float(sumar(filas_cargos, k)) for k in ("bruto", "descuento", "neto")},
                "vacio": "No hay gastos médicos en esas fechas.",
            },
            {
                "titulo": "Cuotas mensuales",
                "columnas": [
                    columna("periodo", "Mes"), columna("monto", "Cuota", "dinero"),
                    columna("estado", "Estado"), columna("fecha_pago", "Pagada el", "fecha"),
                ],
                "filas": filas_cuotas,
                "totales": {"monto": a_float(cuotas_total)},
                "vacio": "No hay cuotas en esas fechas.",
            },
        ],
    }


# -------------------------------------------- RF-40 · pagos a la fundacion

def pagos_a_la_fundacion(pagos: list[dict], deuda: dict) -> dict:
    filas = [{"fecha": p["fecha"], "descripcion": p.get("descripcion") or "—",
              "comprobante": p.get("comprobante") or "—", "monto": p["monto"]}
             for p in sorted(pagos, key=lambda p: p["fecha"])]
    return {
        "titulo": "Pagos realizados a la fundación",
        "requisito": "RF-40",
        "resumen": [
            cifra("Pagado en el período", sumar(filas, "monto")),
            cifra("Servicios de la fundación (total)", dinero(deuda.get("total_servicios"))),
            cifra("Pagado desde el inicio", dinero(deuda.get("total_pagado"))),
            cifra("Se le debe hoy", dinero(deuda.get("saldo"))),
        ],
        "secciones": [{
            "titulo": "Pagos",
            "columnas": [
                columna("fecha", "Fecha", "fecha"), columna("descripcion", "Descripción"),
                columna("comprobante", "Comprobante"), columna("monto", "Monto", "dinero"),
            ],
            "filas": filas,
            "totales": {"monto": a_float(sumar(filas, "monto"))},
            "vacio": "No hay pagos a la fundación en esas fechas.",
        }],
    }


# ------------------------------------ RF-41 · ingresos por donaciones y cobros

def ingresos(donaciones: list[dict], cuotas: list[dict], cargos: list[dict], gastos: list[dict],
             internos: dict, desde: str | None, hasta: str | None) -> dict:
    """
    Lo que entro al asilo en el rango: donaciones y lo que pagaron los
    familiares (cuotas y gastos medicos, por el dia del pago). Los gastos
    van al final para ver el balance.
    """
    filas_donaciones = [{
        "fecha": d["fecha"], "origen": d["origen"], "tipo": NOMBRE_DONANTE.get(d["tipo_donante"], d["tipo_donante"]),
        "monto": d["monto"],
    } for d in sorted(donaciones, key=lambda d: d["fecha"])]

    cobrado = []
    for c in cuotas:
        if c["estado"] == "PAGADA" and en_rango(c.get("fecha_pago"), desde, hasta):
            cobrado.append({"fecha": c["fecha_pago"], "interno": c["paciente_nombre"],
                            "concepto": f"Cuota de {c['periodo']}", "monto": c["monto"]})
    for c in cargos:
        cuando = c.get("fecha_pago") or c["fecha"]
        if c["estado"] == "PAGADO" and en_rango(cuando, desde, hasta):
            cobrado.append({"fecha": cuando, "interno": nombre_interno(internos, c["paciente_id"], c.get("paciente_nombre")),
                            "concepto": c["concepto"], "monto": c["monto_neto"]})
    cobrado.sort(key=lambda x: x["fecha"])

    filas_gastos = [{"fecha": g["fecha"], "categoria": g["categoria"].replace("_", " ").capitalize(),
                     "descripcion": g["descripcion"], "monto": g["monto"]}
                    for g in sorted(gastos, key=lambda g: g["fecha"])]

    total_donaciones = sumar(filas_donaciones, "monto")
    total_cobrado = sumar(cobrado, "monto")
    total_gastos = sumar(filas_gastos, "monto")
    por_tipo = defaultdict(lambda: Decimal("0.00"))
    for d in donaciones:
        por_tipo[d["tipo_donante"]] += dinero(d["monto"])
    return {
        "titulo": "Ingresos por donaciones y cobros",
        "requisito": "RF-41",
        "resumen": [
            cifra("Donaciones", total_donaciones),
            *(cifra(f"De {NOMBRE_DONANTE[t].lower()}", v) for t, v in por_tipo.items()),
            cifra("Cobrado a familiares", total_cobrado),
            cifra("Total de ingresos", total_donaciones + total_cobrado),
            cifra("Gastos de operación", total_gastos),
            cifra("Balance", total_donaciones + total_cobrado - total_gastos),
        ],
        "secciones": [
            {
                "titulo": "Donaciones",
                "columnas": [columna("fecha", "Fecha", "fecha"), columna("origen", "Quién dona"),
                             columna("tipo", "Tipo"), columna("monto", "Monto", "dinero")],
                "filas": filas_donaciones, "totales": {"monto": a_float(total_donaciones)},
                "vacio": "No hay donaciones en esas fechas.",
            },
            {
                "titulo": "Cobrado a los familiares",
                "columnas": [columna("fecha", "Pagado el", "fecha"), columna("interno", "Interno"),
                             columna("concepto", "Concepto"), columna("monto", "Monto", "dinero")],
                "filas": cobrado, "totales": {"monto": a_float(total_cobrado)},
                "vacio": "No hay cobros en esas fechas.",
            },
            {
                "titulo": "Gastos de operación",
                "columnas": [columna("fecha", "Fecha", "fecha"), columna("categoria", "Categoría"),
                             columna("descripcion", "Descripción"), columna("monto", "Monto", "dinero")],
                "filas": filas_gastos, "totales": {"monto": a_float(total_gastos)},
                "vacio": "No hay gastos en esas fechas.",
            },
        ],
    }


# ------------------------------------- RF-42 · examenes realizados

def examenes_realizados(fichas: list[dict], internos: dict, desde: str | None, hasta: str | None) -> dict:
    filas = []
    for f in fichas:
        for o in f.get("examenes", []):
            r = o.get("resultado")
            if not r or not en_rango(r["fecha_resultado"], desde, hasta):
                continue
            filas.append({
                "fecha": r["fecha_resultado"],
                "interno": nombre_interno(internos, f["paciente_id"], f["paciente_nombre"]),
                "examen": o["examen"], "resultado": r["resultado"],
                "ordeno": f"{f['medico']} ({f['especialidad']})", "laboratorio": r.get("responsable") or "—",
            })
    filas.sort(key=lambda x: (x["interno"], x["fecha"]))
    cuantos = Counter(x["examen"] for x in filas)
    return {
        "titulo": "Exámenes médicos realizados por interno",
        "requisito": "RF-42",
        "resumen": [cifra("Exámenes realizados", len(filas), "numero"),
                    cifra("Internos atendidos", len({x["interno"] for x in filas}), "numero"),
                    *(cifra(e, n, "numero") for e, n in cuantos.most_common(5))],
        "secciones": [{
            "titulo": "Exámenes con resultado",
            "columnas": [columna("interno", "Interno"), columna("fecha", "Fecha", "fecha"),
                         columna("examen", "Examen"), columna("resultado", "Resultado"),
                         columna("ordeno", "Lo ordenó"), columna("laboratorio", "Laboratorio")],
            "filas": filas,
            "vacio": "No hay exámenes con resultado en esas fechas.",
        }],
    }


# ------------------------------------- RF-43 · medicamentos aplicados

def medicamentos_aplicados(fichas: list[dict], internos: dict, desde: str | None, hasta: str | None) -> dict:
    filas = []
    for f in fichas:
        for r in f.get("recetas", []):
            d = r.get("despacho")
            if not d or not en_rango(d["fecha"], desde, hasta):
                continue
            filas.append({
                "fecha": d["fecha"],
                "interno": nombre_interno(internos, f["paciente_id"], f["paciente_nombre"]),
                "medicamento": r["medicamento"], "cantidad": d["cantidad_despachada"],
                "indicaciones": r["indicaciones"], "receto": f["medico"], "farmacia": d.get("responsable") or "—",
            })
    filas.sort(key=lambda x: (x["interno"], x["fecha"]))
    return {
        "titulo": "Medicamentos aplicados por interno",
        "requisito": "RF-43",
        "resumen": [cifra("Entregas", len(filas), "numero"),
                    cifra("Unidades entregadas", sum(x["cantidad"] for x in filas), "numero"),
                    cifra("Internos con tratamiento", len({x["interno"] for x in filas}), "numero")],
        "secciones": [{
            "titulo": "Medicamentos entregados",
            "columnas": [columna("interno", "Interno"), columna("fecha", "Entregado el", "fecha"),
                         columna("medicamento", "Medicamento"), columna("cantidad", "Cantidad", "numero"),
                         columna("indicaciones", "Cómo se aplica"), columna("receto", "Lo recetó"),
                         columna("farmacia", "Farmacia")],
            "filas": filas,
            "totales": {"cantidad": sum(x["cantidad"] for x in filas)},
            "vacio": "No hay medicamentos entregados en esas fechas.",
        }],
    }
