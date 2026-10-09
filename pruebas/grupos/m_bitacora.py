"""
M · Bitacora de auditoria

Lo que el gateway promete en main.py: se anota lo que modifica datos y
lo que se rechaza; las lecturas exitosas no; el cuerpo de la peticion
nunca; y solo el Administrador puede consultarla.

Para "el cuerpo nunca se guarda" se manda un valor centinela unico dentro
del cuerpo y luego se busca, como root, en TODAS las columnas de la
tabla. Si aparece en cualquier parte, el cuerpo se filtro.
"""

from apoyo.gateway import NOMBRE_ROL, resumen

LETRA = "M"
TITULO = "Bitácora"
DESCRIPCION = "Qué se anota, qué no, que el cuerpo nunca se guarda y quién puede consultarla."


def ejecutar(ctx) -> None:
    rep, gw = ctx.rep, ctx.gw
    centinela = f"CENTINELA-{ctx.sello}"

    creada = ctx.crear_tarifa(f"M bitacora {centinela}", "EXAMEN", 12.50, 10)
    tarifa_id = creada.json()["id"] if creada.status_code == 201 else None
    lectura = gw.get("CAJA", f"/api/tarifas/{tarifa_id}") if tarifa_id else None
    negado = gw.get("MEDICO_GENERAL", "/api/cargos")

    filas = gw.get(
        "ADMIN", "/api/bitacora", params={"desde": ctx.inicio_sql, "limite": 500}
    ).json()

    with rep.caso(
        "Las operaciones que modifican quedan registradas",
        "Bitácora de auditoría (gateway)",
        "Una fila con usuario caja, rol CAJA, POST /api/tarifas y código 201",
    ) as c:
        if tarifa_id is None:
            raise RuntimeError(f"no se pudo crear la tarifa de apoyo: {resumen(creada)}")
        fila = next(
            (f for f in filas if f["usuario"] == "caja" and f["metodo"] == "POST"
             and f["recurso"] == "/api/tarifas" and f["codigo"] == 201),
            None,
        )
        c.obtenido = (
            f"fila {fila['id']}: {fila['fecha']} · {fila['usuario']} · {fila['rol']} · "
            f"{fila['metodo']} {fila['recurso']} · {fila['codigo']}"
            if fila else "no se encontró la fila de la creación"
        )
        c.pasa = fila is not None and fila["rol"] == "CAJA"

    with rep.caso(
        "Las lecturas exitosas no quedan registradas",
        "Bitácora de auditoría (gateway)",
        f"Ninguna fila para GET /api/tarifas/{tarifa_id} con 200",
    ) as c:
        if lectura is None:
            raise RuntimeError("no hubo lectura que comprobar")
        encontradas = [
            f for f in filas
            if f["metodo"] == "GET" and f["recurso"] == f"/api/tarifas/{tarifa_id}"
        ]
        c.obtenido = f"lectura: {lectura.status_code} · filas en la bitácora para esa lectura: {len(encontradas)}"
        c.pasa = lectura.status_code == 200 and not encontradas

    with rep.caso(
        "Los rechazos sí quedan registrados, aunque sean lecturas",
        "Bitácora de auditoría (gateway)",
        "Una fila con usuario medico, GET /api/cargos y código 403",
    ) as c:
        fila = next(
            (f for f in filas if f["usuario"] == "medico" and f["metodo"] == "GET"
             and f["recurso"] == "/api/cargos" and f["codigo"] == 403),
            None,
        )
        c.obtenido = (
            f"petición: {negado.status_code} · "
            + (f"fila {fila['id']}: {fila['usuario']} · {fila['metodo']} {fila['recurso']} · {fila['codigo']}"
               if fila else "no se encontró la fila del rechazo")
        )
        c.pasa = negado.status_code == 403 and fila is not None

    with rep.caso(
        "El cuerpo de la petición no se guarda",
        "Bitácora de auditoría (gateway)",
        "La tabla no tiene columna para el cuerpo, y ni el valor centinela enviado en "
        "el cuerpo ni la contraseña de ingreso aparecen en ninguna fila",
    ) as c:
        columnas = [
            f["COLUMN_NAME"] for f in ctx.root.consulta(
                """SELECT COLUMN_NAME FROM information_schema.COLUMNS
                   WHERE TABLE_SCHEMA = 'asilo_gateway' AND TABLE_NAME = 'bitacora'
                   ORDER BY ORDINAL_POSITION"""
            )
        ]
        todo = "CONCAT_WS('|', " + ", ".join(f"`{k}`" for k in columnas) + ")"
        con_centinela = ctx.root.uno(
            f"SELECT COUNT(*) FROM asilo_gateway.bitacora WHERE {todo} LIKE %s", (f"%{centinela}%",)
        )
        con_contrasena = ctx.root.uno(
            f"SELECT COUNT(*) FROM asilo_gateway.bitacora WHERE {todo} LIKE %s", (f"%{ctx.contrasena}%",)
        )
        c.obtenido = (
            f"columnas: {', '.join(columnas)} · filas con el centinela: {con_centinela} · "
            f"filas con la contraseña: {con_contrasena}"
        )
        c.pasa = con_centinela == 0 and con_contrasena == 0

    with rep.caso(
        "Solo el Administrador consulta la bitácora",
        "Bitácora de auditoría · matriz de permisos",
        "Administrador 200; los otros cuatro roles 403; sin sesión 401",
    ) as c:
        partes, bien = [], True
        for rol in ("ADMIN", "SECRETARIA", "MEDICO_GENERAL", "FUNDACION", "CAJA"):
            r = gw.get(rol, "/api/bitacora", params={"limite": 1})
            debe = 200 if rol == "ADMIN" else 403
            partes.append(f"{NOMBRE_ROL[rol]}: {r.status_code}")
            bien &= r.status_code == debe
        anonimo = gw.get(None, "/api/bitacora")
        partes.append(f"sin sesión: {anonimo.status_code}")
        bien &= anonimo.status_code == 401
        c.obtenido = " · ".join(partes)
        c.pasa = bien
