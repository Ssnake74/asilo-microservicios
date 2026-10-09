"""
L · Notificacion por correo (RF-44)

Al registrar una remision, el familiar recibe un aviso. El envio ocurre
DESPUES de responder al medico (tarea de fondo), asi que un servidor de
correo lento o caido no debe demorar ni impedir la remision.

Mailpit NO se detiene en ninguna prueba. Guarda los mensajes en una base
temporal que se borra al apagarse, y la bandeja tiene que quedar intacta.
Las dos formas de dejarlo sin servicio que se usan aqui conservan todo:

  pausado        el proceso queda congelado: la conexion se abre pero
                 nunca contesta. Es el peor caso para la demora.
  desconectado   se le quita la red: el nombre "mailpit" deja de existir
                 para los demas, como si estuviera apagado.

Los correos de prueba van a direcciones @example.com con el sello de la
corrida, y se borran de la bandeja al terminar; los demas no se tocan.
"""

import time

from apoyo import correo
from apoyo.gateway import resumen

LETRA = "L"
TITULO = "Notificación por correo"
DESCRIPCION = (
    "Aviso al familiar al registrar una remisión. Mailpit nunca se detiene: se "
    "pausa o se desconecta de la red, para no perder la bandeja."
)

MAILPIT = "asilo-mailpit"
# El aviso se manda con un limite de 10 s (notificaciones.py). Se espera un
# poco mas antes de reanudar Mailpit para que ese intento ya haya vencido
# y no entregue el correo tarde, confundiendo el resultado.
ESPERA_TRAS_PAUSA = 12
LIMITE_RESPUESTA = 2.0


def direccion(ctx, caso: str) -> str:
    return f"prueba.auto.{ctx.sello}.{caso}@example.com"


def remision_guardada(ctx, solicitud_id: int) -> bool:
    return ctx.gw.get("MEDICO_GENERAL", f"/api/solicitudes/{solicitud_id}").status_code == 200


def ejecutar(ctx) -> None:
    rep, docker = ctx.rep, ctx.docker
    paciente = ctx.interno("L correo")

    with rep.caso(
        "Remisión con correo del familiar",
        "RF-44",
        "201, y en la bandeja aparece un mensaje para ese correo con el nombre del "
        "interno en el asunto y la especialidad en el texto",
    ) as c:
        destino = direccion(ctx, "l1")
        r = ctx.crear_remision(paciente, "Cardiologia", correo=destino, etiqueta="L con correo")
        llegados = correo.esperar(f'to:"{destino}"', 20)
        if not llegados:
            c.obtenido = f"remisión: {resumen(r) if r.status_code != 201 else '201'} · no llegó ningún mensaje en 20 s"
        else:
            m = correo.mensaje(llegados[0]["ID"])
            asunto = m.get("Subject", "")
            texto = m.get("Text", "")
            c.obtenido = (
                f"remisión: {r.status_code} · mensajes para {destino}: {len(llegados)} · "
                f"asunto «{asunto}» · especialidad en el texto: "
                f"{'sí' if 'Cardiologia' in texto else 'NO'}"
            )
            c.pasa = (
                r.status_code == 201 and len(llegados) == 1
                and paciente["apellidos"] in asunto and "Cardiologia" in texto
            )

    with rep.caso(
        "Remisión sin correo del familiar",
        "RF-44 (flujo alterno)",
        "201, la remisión queda guardada y no se envía ningún mensaje",
    ) as c:
        sin_correo = ctx.interno("L sin correo")
        r = ctx.crear_remision(sin_correo, "Geriatria", correo=None, etiqueta="L sin correo")
        time.sleep(4)
        llegados = correo.buscar(f'subject:"{sin_correo["apellidos"]}"')
        guardada = r.status_code == 201 and remision_guardada(ctx, r.json()["id"])
        c.obtenido = (
            f"remisión: {r.status_code} · guardada: {'sí' if guardada else 'NO'} · "
            f"mensajes enviados: {len(llegados)}"
        )
        c.pasa = guardada and not llegados

    with rep.caso(
        "Remisión con el servidor de correo pausado (no responde)",
        "RF-44 y RNF-11",
        f"201 en menos de {LIMITE_RESPUESTA:.0f} s, la remisión queda guardada y la "
        "bandeja conserva sus mensajes",
    ) as c:
        antes = correo.total()
        docker.pausar(MAILPIT)
        try:
            inicio = time.time()
            r = ctx.crear_remision(paciente, "Neumologia", correo=direccion(ctx, "l3"), etiqueta="L pausado")
            demora = time.time() - inicio
            guardada = r.status_code == 201 and remision_guardada(ctx, r.json()["id"])
            time.sleep(ESPERA_TRAS_PAUSA)
        finally:
            docker.reanudar(MAILPIT)
        despues = correo.total()
        c.obtenido = (
            f"remisión: {r.status_code} en {demora:.2f} s · guardada: {'sí' if guardada else 'NO'} · "
            f"mensajes en la bandeja antes {antes}, después {despues}"
        )
        c.pasa = guardada and demora < LIMITE_RESPUESTA and despues >= antes

    with rep.caso(
        "Remisión con el servidor de correo desconectado de la red",
        "RF-44 y RNF-11",
        f"201 en menos de {LIMITE_RESPUESTA:.0f} s y la remisión queda guardada; al "
        "reconectarlo, la bandeja conserva sus mensajes",
    ) as c:
        alias = ctx.inicial["alias_correo"]
        destino = direccion(ctx, "l4")
        antes = correo.total()
        docker.desconectar(ctx.red, MAILPIT)
        try:
            inicio = time.time()
            r = ctx.crear_remision(paciente, "Neurologia", correo=destino, etiqueta="L desconectado")
            demora = time.time() - inicio
            guardada = r.status_code == 201 and remision_guardada(ctx, r.json()["id"])
            time.sleep(2)
        finally:
            docker.conectar(ctx.red, MAILPIT, alias)
        for _ in range(20):
            if correo.responde():
                break
            time.sleep(0.5)
        # Mientras Mailpit no esta en la red, buscar su nombre tarda varios
        # segundos en fallar, y si en ese rato vuelve, el aviso termina
        # saliendo. Se espera a ver si llega, para dejarlo dicho en el
        # reporte y para que la limpieza no lo encuentre despues.
        tardio = correo.esperar(f'to:"{destino}"', 25)
        despues = correo.total() - len(tardio)
        c.obtenido = (
            f"remisión: {r.status_code} en {demora:.2f} s · guardada: {'sí' if guardada else 'NO'} · "
            f"mensajes en la bandeja antes {antes}, después {despues} (sin contar el aviso de "
            f"esta remisión) · reconectado con los alias {', '.join(alias)} · el aviso "
            + ("se entregó al volver Mailpit a la red" if tardio else "no se entregó")
        )
        c.pasa = guardada and demora < LIMITE_RESPUESTA and despues >= antes
