"""
D · Control de acceso por rol (RNF-02)

Recorre la matriz de permisos de la seccion 8 del ERS: cada operacion
que el sistema declara, contra cada uno de los cinco roles.

La matriz esta copiada aqui del ERS a proposito, y NO se importa de
gateway/app/seguridad.py: si se importara, la prueba compararia el
codigo consigo mismo y no podria fallar nunca. Lo que se verifica es
que el sistema hace lo que dice el documento.

Como se prueba una operacion permitida sin crear datos: se manda un
cuerpo vacio o un identificador que no existe. Si el gateway deja pasar
la peticion, contesta el MICROSERVICIO, con su propio 422 o 404; si no la
deja pasar, contesta el gateway con 403. Asi se distingue quien respondio
sin dejar ni un registro creado.

Las combinaciones que el sistema no declara (PUT sobre cargos, DELETE
sobre el estado de cuenta...) no se recorren una por una: se agrupan en
dos casos que comprueban la negacion por omision.
"""

from apoyo.gateway import NOMBRE_ROL, ROLES, detalle, resumen

LETRA = "D"
TITULO = "Control de acceso por rol"
DESCRIPCION = (
    "Matriz de permisos del ERS (sección 8): cada operación declarada contra los "
    "cinco roles. «Permitido» significa que la petición atraviesa el gateway y "
    "responde el servicio; «Negado», que el gateway la corta con 403."
)

A, S, M, F, C = "ADMIN", "SECRETARIA", "MEDICO_GENERAL", "FUNDACION", "CAJA"
NO_EXISTE = 999999999

# Por que responde ese codigo el servicio cuando la peticion SI pasa.
RAZON = {
    200: "",
    404: ", registro inexistente",
    422: ", cuerpo vacío",
}

# (recurso en el ERS, operacion en el ERS, metodo, ruta, parametros,
#  cuerpo, codigo del servicio si pasa, roles con permiso segun el ERS)
MATRIZ = [
    ("Internos", "Consultar", "GET", "/api/pacientes", {"buscar": "NOEXISTE"}, None, 200, {A, S, M, F, C}),
    ("Internos", "Registrar", "POST", "/api/pacientes", None, {}, 422, {A, S}),
    ("Internos", "Modificar", "PUT", "/api/pacientes/PAC-NOEXISTE", None, {"habitacion": "X"}, 404, {A, S}),
    ("Internos", "Eliminar", "DELETE", "/api/pacientes/PAC-NOEXISTE", None, None, 404, {A}),
    ("Remisiones", "Consultar", "GET", "/api/solicitudes", {"paciente_id": "NOEXISTE"}, None, 200, {A, S, M, F}),
    ("Remisiones", "Registrar", "POST", "/api/solicitudes", None, {}, 422, {A, M, F}),
    ("Remisiones", "Anular", "DELETE", f"/api/solicitudes/{NO_EXISTE}", None, None, 404, {A, M}),
    ("Visitas", "Consultar", "GET", "/api/visitas", {"paciente_id": "NOEXISTE"}, None, 200, {A, S, M, F}),
    ("Tarifario", "Consultar", "GET", "/api/tarifas", None, None, 200, {A, S, M, F, C}),
    ("Tarifario", "Modificar: crear", "POST", "/api/tarifas", None, {}, 422, {A, C}),
    ("Tarifario", "Modificar: editar", "PUT", f"/api/tarifas/{NO_EXISTE}", None, {"precio": 1}, 404, {A, C}),
    ("Tarifario", "Modificar: eliminar", "DELETE", f"/api/tarifas/{NO_EXISTE}", None, None, 404, {A, C}),
    ("Cargos", "Consultar", "GET", "/api/cargos", {"paciente_id": "NOEXISTE"}, None, 200, {A, S, C}),
    ("Cargos", "Registrar", "POST", "/api/cargos", None, {}, 422, {A, F, C}),
    ("Cargos", "Anular", "DELETE", f"/api/cargos/{NO_EXISTE}", None, None, 404, {A, C}),
    ("Estado de cuenta", "Consultar", "GET", "/api/estado-cuenta/NOEXISTE", None, None, 200, {A, S, C}),
]

# El 404 propio del gateway, que NO cuenta como "llego al servicio".
NO_EXISTE_RECURSO = "Ese recurso no existe en el sistema."

# Combinaciones que el sistema no declara en ninguna parte.
NO_DECLARADAS = [
    ("PUT", f"/api/cargos/{NO_EXISTE}"),
    ("PUT", f"/api/solicitudes/{NO_EXISTE}"),
    ("POST", "/api/visitas"),
    ("DELETE", f"/api/visitas/{NO_EXISTE}"),
    ("POST", "/api/estado-cuenta/NOEXISTE"),
    ("DELETE", "/api/estado-cuenta/NOEXISTE"),
    ("PATCH", "/api/pacientes/PAC-NOEXISTE"),
]


def ejecutar(ctx) -> None:
    rep, gw = ctx.rep, ctx.gw

    for recurso, operacion, metodo, ruta, params, cuerpo, codigo, permitidos in MATRIZ:
        for rol in ROLES:
            permitido = rol in permitidos
            if permitido:
                esperado = f"Permitido: responde el servicio ({codigo}{RAZON[codigo]})"
            else:
                esperado = "Negado: 403 del gateway"

            with rep.caso(
                f"{NOMBRE_ROL[rol]} → {recurso} · {operacion} ({metodo})",
                "RNF-02 · matriz de permisos del ERS",
                esperado,
            ) as c:
                r = gw.pedir(metodo, ruta, gw.como(rol), json=cuerpo, params=params)
                c.obtenido = resumen(r)
                if permitido:
                    c.pasa = r.status_code == codigo and detalle(r) != NO_EXISTE_RECURSO
                else:
                    c.pasa = r.status_code == 403

    with rep.caso(
        "Operaciones no declaradas se niegan incluso al Administrador",
        "RNF-02 · negación por omisión",
        "403 en todas: el Administrador no tiene un permiso comodín",
    ) as c:
        lineas, todas = [], True
        for metodo, ruta in NO_DECLARADAS:
            r = gw.pedir(metodo, ruta, gw.como(A), json={} if metodo in ("POST", "PUT", "PATCH") else None)
            lineas.append(f"{metodo} {ruta} → {r.status_code}")
            todas &= r.status_code == 403
        c.obtenido = "\n".join(lineas)
        c.pasa = todas

    with rep.caso(
        "Ningún rol puede usar una operación no declarada",
        "RNF-02 · negación por omisión",
        "403 para los cinco roles en PUT /api/cargos y DELETE /api/visitas",
    ) as c:
        lineas, todas = [], True
        for rol in ROLES:
            codigos = []
            for metodo, ruta in (("PUT", f"/api/cargos/{NO_EXISTE}"), ("DELETE", f"/api/visitas/{NO_EXISTE}")):
                r = gw.pedir(metodo, ruta, gw.como(rol), json={} if metodo == "PUT" else None)
                codigos.append(r.status_code)
                todas &= r.status_code == 403
            lineas.append(f"{NOMBRE_ROL[rol]}: {', '.join(map(str, codigos))}")
        c.obtenido = " · ".join(lineas)
        c.pasa = todas
