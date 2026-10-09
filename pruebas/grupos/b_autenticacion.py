"""
B · Autenticacion

Ingreso, cierre de sesion y rechazo de peticiones sin sesion (CU-01,
CU-02). Las sesiones que se abren aqui quedan guardadas por rol y las
reutilizan los grupos siguientes.
"""

from apoyo.gateway import NOMBRE_ROL, ROLES, USUARIO_DE_ROL, detalle, resumen

LETRA = "B"
TITULO = "Autenticación"
DESCRIPCION = "Ingreso con los cinco usuarios, rechazos, cierre de sesión y peticiones sin sesión."


def ejecutar(ctx) -> None:
    rep, gw = ctx.rep, ctx.gw

    for rol in ROLES:
        usuario = USUARIO_DE_ROL[rol]
        with rep.caso(
            f"Ingreso válido como «{usuario}» ({NOMBRE_ROL[rol]})",
            "CU-01",
            f"200, sesión abierta con rol {rol}",
        ) as c:
            r = gw.ingresar(usuario)
            if r.status_code == 200:
                datos = r.json()
                ctx.gw.sesion_de_rol[rol] = gw.testigo_de(r)
                c.obtenido = (
                    f"200 · rol {datos['rol']} · «{datos['nombre']}» · "
                    f"recursos visibles: {', '.join(datos['recursos'])}"
                )
                c.pasa = datos["rol"] == rol and bool(gw.testigo_de(r))
            else:
                c.obtenido = resumen(r)

    # El mismo par de rechazos se usa en el caso que compara los mensajes.
    clave_mala = gw.ingresar("admin", "contrasena-equivocada")
    inexistente = gw.ingresar(f"noexiste{ctx.sello}", ctx.contrasena)

    with rep.caso(
        "Contraseña incorrecta",
        "CU-01 (flujo alterno)",
        "401 «Usuario o contraseña incorrectos.» y sin sesión",
    ) as c:
        c.obtenido = resumen(clave_mala)
        c.pasa = clave_mala.status_code == 401 and not gw.testigo_de(clave_mala)

    with rep.caso(
        "Usuario inexistente",
        "CU-01 (flujo alterno)",
        "401 «Usuario o contraseña incorrectos.» y sin sesión",
    ) as c:
        c.obtenido = resumen(inexistente)
        c.pasa = inexistente.status_code == 401 and not gw.testigo_de(inexistente)

    with rep.caso(
        "Usuario y contraseña vacíos",
        "CU-01 (validación de entrada)",
        "Rechazado con 422 antes de consultar la base, sin sesión",
    ) as c:
        r = gw.pedir("POST", "/api/login", json={"usuario": "", "contrasena": ""})
        c.obtenido = resumen(r)
        c.pasa = r.status_code == 422 and not gw.testigo_de(r)

    with rep.caso(
        "El mensaje no revela qué usuarios existen",
        "CU-01 (seguridad del ingreso)",
        "Mismo código y mismo mensaje, letra por letra, para usuario inexistente y "
        "para contraseña incorrecta",
    ) as c:
        a, b = detalle(clave_mala), detalle(inexistente)
        c.obtenido = (
            f"contraseña incorrecta: {clave_mala.status_code} «{a}»\n"
            f"usuario inexistente:   {inexistente.status_code} «{b}»"
        )
        c.pasa = clave_mala.status_code == inexistente.status_code and a == b and a is not None

    with rep.caso(
        "El cierre de sesión invalida el testigo",
        "CU-02",
        "Con el testigo antes del cierre /api/yo da 200; después del cierre, el "
        "mismo testigo da 401",
    ) as c:
        r = gw.ingresar("secretaria")
        testigo = gw.testigo_de(r)
        antes = gw.pedir("GET", "/api/yo", testigo)
        cierre = gw.pedir("POST", "/api/logout", testigo)
        despues = gw.pedir("GET", "/api/yo", testigo)
        c.obtenido = (
            f"antes: {antes.status_code} · cierre: {resumen(cierre)} · "
            f"después: {resumen(despues)}"
        )
        c.pasa = antes.status_code == 200 and cierre.status_code == 200 and despues.status_code == 401

    with rep.caso(
        "Petición sin sesión",
        "CU-01 (precondición de todo recurso)",
        "401 «Debe iniciar sesión.»",
    ) as c:
        r = gw.pedir("GET", "/api/pacientes")
        c.obtenido = resumen(r)
        c.pasa = r.status_code == 401
