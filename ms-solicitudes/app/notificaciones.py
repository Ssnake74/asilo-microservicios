"""
Aviso por correo al familiar del interno (RF-44).

El envio va en try/except y nunca tumba la remision (RNF-11): si el
servidor de correo no responde, se anota en el log. Se llama con
BackgroundTasks, despues de responderle al medico.

El texto del correo lleva tildes porque lo lee el familiar.
"""

import os
import smtplib
from datetime import datetime
from email.message import EmailMessage
from html import escape

# Configuracion del servidor de correo. Los valores por omision son los
# del docker-compose para que el servicio tambien arranque si alguien
# olvida declarar las variables.
SMTP_HOST = os.getenv("SMTP_HOST", "mailpit")
SMTP_PORT = int(os.getenv("SMTP_PORT", "1025"))
SMTP_REMITENTE = os.getenv("SMTP_REMITENTE", "notificaciones@asilocabezadealgodon.org")

# Con el servidor de correo caido, conectarse puede quedarse colgado: el
# limite evita que la tarea de fondo ocupe un hilo indefinidamente.
TIMEOUT = 10.0

ASILO = 'Asilo de Ancianos "Cabeza de Algodón"'

MESES = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
)


def _fecha_en_palabras(fecha_solicitud: str) -> str:
    """
    De "2026-09-22 15:26:03" a "22 de septiembre de 2026".

    Si la fecha no viene en ese formato se devuelve tal cual: un correo
    con la fecha fea es mejor que ningun correo.
    """
    try:
        fecha = datetime.strptime(fecha_solicitud, "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return str(fecha_solicitud)
    return f"{fecha.day} de {MESES[fecha.month - 1]} de {fecha.year}"


def _cuerpo_texto(solicitud: dict, fecha: str) -> str:
    """
    Version en texto plano del aviso.

    Va para el familiar, que no conoce el sistema: no habla de
    "solicitudes" ni "estados", sino de que lo va a ver un especialista.
    """
    return f"""Estimada familia:

Le saludamos del {ASILO}.

Le escribimos para informarle que el {fecha}, nuestro médico general,
{solicitud['medico_general']}, revisó a {solicitud['paciente_nombre']} y
considera conveniente que pase consulta con un especialista en
{solicitud['especialidad_remitida']}.

Motivo de la remisión:
{solicitud['motivo']}

La fundación se encargará de asignar el médico especialista y el horario
de la consulta. En cuanto queden definidos, nos comunicaremos con usted
para informarle el día y la hora.

Si desea consultar algo sobre el estado de su familiar, con gusto le
atendemos en la administración del asilo.

Atentamente,
{ASILO}
"""


def _cuerpo_html(solicitud: dict, fecha: str) -> str:
    """
    Version en HTML del mismo aviso.

    Sin imagenes ni recursos de internet, para que se vea completo aunque
    el lector bloquee el contenido externo. Los estilos van en cada
    etiqueta porque varios lectores descartan el bloque <style>.

    El motivo y los nombres son texto libre y se escapan: un "<" en el
    motivo no debe romper el correo.
    """
    paciente = escape(solicitud["paciente_nombre"])
    especialidad = escape(solicitud["especialidad_remitida"])
    medico = escape(solicitud["medico_general"])
    motivo = escape(solicitud["motivo"])
    asilo = escape(ASILO)

    return f"""<!DOCTYPE html>
<html lang="es">
<head><meta charset="utf-8"></head>
<body style="margin:0; padding:24px; background:#f4f4f2;
             font-family: Georgia, 'Times New Roman', serif; color:#2b2b2b;">
  <div style="max-width:600px; margin:0 auto; background:#ffffff;
              border:1px solid #d8d5cd; padding:32px;">

    <p style="margin:0 0 4px; font-size:17px; font-weight:bold;">{asilo}</p>
    <p style="margin:0 0 24px; font-size:13px; color:#6b6b6b;">
      Aviso para la familia
    </p>

    <p style="margin:0 0 16px; font-size:15px; line-height:1.6;">
      Estimada familia:
    </p>

    <p style="margin:0 0 16px; font-size:15px; line-height:1.6;">
      Le escribimos para informarle que el <strong>{fecha}</strong>, nuestro
      médico general, {medico}, revisó a <strong>{paciente}</strong> y
      considera conveniente que pase consulta con un especialista en
      <strong>{especialidad}</strong>.
    </p>

    <p style="margin:0 0 6px; font-size:13px; color:#6b6b6b;
              text-transform:uppercase; letter-spacing:0.5px;">
      Motivo de la remisión
    </p>
    <p style="margin:0 0 24px; padding:12px 16px; background:#f7f6f3;
              border-left:3px solid #b9b3a5; font-size:15px; line-height:1.6;">
      {motivo}
    </p>

    <p style="margin:0 0 16px; font-size:15px; line-height:1.6;">
      La fundación se encargará de asignar el médico especialista y el
      horario de la consulta. En cuanto queden definidos, nos comunicaremos
      con usted para informarle el día y la hora.
    </p>

    <p style="margin:0 0 24px; font-size:15px; line-height:1.6;">
      Si desea consultar algo sobre el estado de su familiar, con gusto le
      atendemos en la administración del asilo.
    </p>

    <p style="margin:0; padding-top:20px; border-top:1px solid #e3e0d8;
              font-size:14px; line-height:1.6;">
      Atentamente,<br>
      <strong>{asilo}</strong>
    </p>

  </div>
</body>
</html>
"""


def avisar_al_familiar(solicitud: dict) -> None:
    """
    Envia el aviso de la remision al familiar del interno.

    Recibe la fila completa de la solicitud para no volver a consultar la
    base desde la tarea de fondo.

    No devuelve nada ni levanta excepciones: corre cuando el medico ya
    recibio su confirmacion, y un error solo puede ir al log.
    """
    destinatario = (solicitud.get("familiar_email") or "").strip()

    # Un interno sin correo de familiar es un caso normal, no un error: se
    # anota por que no salio el aviso y se sigue.
    if not destinatario:
        print(
            f"[ms-solicitudes] La remision {solicitud['id']} de "
            f"{solicitud['paciente_nombre']} no tiene correo de familiar "
            "registrado: no se envio el aviso.",
            flush=True,
        )
        return

    try:
        fecha = _fecha_en_palabras(solicitud["fecha_solicitud"])

        mensaje = EmailMessage()
        mensaje["Subject"] = (
            f"Solicitud de consulta médica para {solicitud['paciente_nombre']}"
        )
        mensaje["From"] = SMTP_REMITENTE
        mensaje["To"] = destinatario
        # Texto plano primero y HTML como alternativa: un lector que no
        # muestra HTML recibe igual el aviso completo.
        mensaje.set_content(_cuerpo_texto(solicitud, fecha))
        mensaje.add_alternative(_cuerpo_html(solicitud, fecha), subtype="html")

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=TIMEOUT) as servidor:
            servidor.send_message(mensaje)

        print(
            f"[ms-solicitudes] Aviso de la remision {solicitud['id']} enviado "
            f"a {destinatario}.",
            flush=True,
        )
    # Except amplio a proposito: ningun fallo del correo justifica perder la
    # remision, que ya esta guardada. Se anota con el numero de remision
    # para poder reenviar el aviso a mano.
    except Exception as error:
        print(
            f"[ms-solicitudes] No se pudo enviar el aviso de la remision "
            f"{solicitud['id']} a {destinatario}: {error}",
            flush=True,
        )
