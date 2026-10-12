"""
N · Vencimiento de la sesion

RF-05: la sesion expira tras ocho horas sin actividad. Para no esperar
ocho horas, se mueve la fecha de vencimiento como root y se mira que hace
el gateway con la siguiente peticion.
"""

from apoyo.gateway import resumen

LETRA = "N"
TITULO = "Vencimiento de la sesión"
DESCRIPCION = "Cada petición renueva las ocho horas y una sesión vencida no vuelve a entrar."

MINUTOS_QUE_QUEDAN = (
    "SELECT TIMESTAMPDIFF(MINUTE, NOW(), expira) FROM asilo_gateway.sesiones WHERE token = %s"
)
MOVER_VENCIMIENTO = (
    "UPDATE asilo_gateway.sesiones SET expira = NOW() + INTERVAL %s MINUTE WHERE token = %s"
)


def ejecutar(ctx) -> None:
    rep, gw, root = ctx.rep, ctx.gw, ctx.root

    with rep.caso(
        "Cada petición renueva la sesión",
        "RF-05",
        "A una sesión que vencía en 5 minutos le quedan ocho horas después de una petición",
    ) as c:
        testigo = gw.testigo_de(gw.ingresar("secretaria"))
        root.ejecutar(MOVER_VENCIMIENTO, (5, testigo))
        antes = root.uno(MINUTOS_QUE_QUEDAN, (testigo,))
        r = gw.pedir("GET", "/api/yo", testigo)
        despues = root.uno(MINUTOS_QUE_QUEDAN, (testigo,))
        c.obtenido = f"antes: {antes} min · petición: {r.status_code} · después: {despues} min"
        c.pasa = (
            r.status_code == 200
            and antes is not None and antes <= 5
            and despues is not None and despues >= 478
        )

    with rep.caso(
        "Una sesión vencida no entra ni se renueva",
        "RF-05",
        "401 «Su sesión venció. Vuelva a entrar.» y la sesión sigue vencida",
    ) as c:
        testigo = gw.testigo_de(gw.ingresar("secretaria"))
        root.ejecutar(MOVER_VENCIMIENTO, (-1, testigo))
        r = gw.pedir("GET", "/api/yo", testigo)
        despues = root.uno(MINUTOS_QUE_QUEDAN, (testigo,))
        c.obtenido = f"{resumen(r)} · le quedan: {despues} min"
        c.pasa = r.status_code == 401 and (despues is None or despues < 0)
