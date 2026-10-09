"""
C · Bloqueo por intentos fallidos

Cinco fallos en quince minutos cierran el ingreso (gateway/app/db.py).
Se bloquea a proposito la cuenta «caja», que es una cuenta real, porque
el caso "la contrasena correcta tampoco entra" solo tiene sentido con un
usuario que exista.

Al terminar el grupo se borran los intentos que creo la corrida. Solo
esos: se usa el id mas alto que habia al empezar, asi que si existian
intentos de antes, quedan como estaban.
"""

from apoyo.gateway import detalle, resumen

LETRA = "C"
TITULO = "Bloqueo por intentos fallidos"
DESCRIPCION = (
    "Cinco fallos seguidos bloquean el ingreso durante quince minutos, exista o no "
    "el usuario. Se usa la cuenta «caja»; al final del grupo se desbloquea."
)

CUENTA = "caja"


def intentos_de(ctx, usuario: str) -> int:
    return ctx.root.uno(
        "SELECT COUNT(*) FROM asilo_gateway.intentos_fallidos WHERE usuario = %s", (usuario,)
    )


def ejecutar(ctx) -> None:
    rep, gw = ctx.rep, ctx.gw
    fantasma = f"fantasma{ctx.sello}"

    # Por si la cuenta ya traia fallos de los grupos anteriores: el conteo
    # de este grupo tiene que empezar en cero para que "cinco" sea cinco.
    ctx.root.ejecutar(
        "DELETE FROM asilo_gateway.intentos_fallidos WHERE usuario IN (%s, %s) AND id > %s",
        (CUENTA, fantasma, ctx.inicial["max_intentos"]),
    )

    bloqueo_real = None

    with rep.caso(
        "Cinco contraseñas incorrectas seguidas",
        "CU-01 (bloqueo de ingreso)",
        "Los cinco intentos responden 401",
    ) as c:
        codigos = [gw.ingresar(CUENTA, "equivocada-1").status_code for _ in range(5)]
        c.obtenido = ", ".join(map(str, codigos)) + f" · fallos anotados: {intentos_de(ctx, CUENTA)}"
        c.pasa = codigos == [401] * 5

    with rep.caso(
        "Sexto intento con contraseña incorrecta",
        "CU-01 (bloqueo de ingreso)",
        "429 con un mensaje que indica cuántos minutos faltan",
    ) as c:
        r = gw.ingresar(CUENTA, "equivocada-1")
        bloqueo_real = r
        c.obtenido = resumen(r)
        c.pasa = r.status_code == 429 and "minuto" in (detalle(r) or "")

    with rep.caso(
        "Sexto intento con la contraseña CORRECTA",
        "CU-01 (bloqueo de ingreso)",
        "429: el bloqueo se revisa antes que la contraseña",
    ) as c:
        r = gw.ingresar(CUENTA)
        c.obtenido = resumen(r)
        c.pasa = r.status_code == 429 and not gw.testigo_de(r)

    with rep.caso(
        "Un usuario inexistente se bloquea igual",
        "CU-01 (no revelar qué usuarios existen)",
        "Cinco 401 y luego 429, con el mismo mensaje de bloqueo que un usuario real",
    ) as c:
        codigos = [gw.ingresar(fantasma, "equivocada-1").status_code for _ in range(5)]
        sexto = gw.ingresar(fantasma, "equivocada-1")
        codigos.append(sexto.status_code)
        igual = bloqueo_real is not None and detalle(sexto) == detalle(bloqueo_real)
        c.obtenido = (
            f"«{fantasma}»: {', '.join(map(str, codigos))} · "
            f"mensaje {'idéntico' if igual else 'DISTINTO'} al de «{CUENTA}»: «{detalle(sexto)}»"
        )
        c.pasa = codigos == [401] * 5 + [429] and igual

    with rep.caso(
        "Un ingreso correcto limpia los intentos anteriores",
        "CU-01 (bloqueo de ingreso)",
        "Tras tres fallos de «secretaria», el ingreso correcto deja su conteo en 0",
    ) as c:
        for _ in range(3):
            gw.ingresar("secretaria", "equivocada-2")
        antes = intentos_de(ctx, "secretaria")
        r = gw.ingresar("secretaria")
        despues = intentos_de(ctx, "secretaria")
        c.obtenido = f"fallos antes: {antes} · ingreso: {r.status_code} · fallos después: {despues}"
        c.pasa = antes >= 3 and r.status_code == 200 and despues == 0

    # Limpieza del grupo, pedida expresamente: no dejar cuentas bloqueadas.
    borrados = ctx.root.ejecutar(
        "DELETE FROM asilo_gateway.intentos_fallidos WHERE id > %s", (ctx.inicial["max_intentos"],)
    )

    with rep.caso(
        "Limpieza: ninguna cuenta queda bloqueada",
        "Limpieza del grupo C",
        "Sin intentos de la corrida en la tabla y «caja» vuelve a entrar con 200",
    ) as c:
        restantes = ctx.root.uno(
            "SELECT COUNT(*) FROM asilo_gateway.intentos_fallidos WHERE id > %s",
            (ctx.inicial["max_intentos"],),
        )
        r = gw.ingresar(CUENTA)
        c.obtenido = (
            f"filas de intentos borradas: {borrados} · quedan de la corrida: {restantes} · "
            f"ingreso de «{CUENTA}»: {resumen(r)}"
        )
        c.pasa = restantes == 0 and r.status_code == 200
