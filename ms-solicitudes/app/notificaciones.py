"""
Aviso por correo al familiar del interno (RF-44).

Cuando el medico general registra una remision, el familiar recibe un
correo contandole que a su pariente lo van a ver con un especialista.

El envio es hacia AFUERA del sistema, igual que la llamada de
cliente_cobros.py al microservicio de Cobros, y se trata con el mismo
criterio (RNF-11): va envuelto en try/except y nunca puede tumbar la
operacion principal. Si el servidor de correo no responde, la remision
ya quedo guardada y lo unico que pasa es que se anota en el log.

Quien llama a este modulo lo hace con BackgroundTasks, asi que el envio
ocurre DESPUES de haberle respondido al medico: el no espera a que el
correo salga para que la pantalla le confirme la remision.

Nota sobre las tildes: los nombres del codigo van sin ellas, como en
todo el proyecto, pero el texto del correo SI las lleva. Ese texto no lo
lee un programador, lo lee la hija o el hijo de un interno, y una
institucion que escribe "remision" y "medico" sin tilde se ve descuidada.

En desarrollo el servidor de correo es Mailpit, que recibe los mensajes
pero no los manda a internet: se leen en http://localhost:8025. Para el
servidor de la universidad basta con cambiar las variables de entorno,
sin tocar este archivo.
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

# Si el servidor de correo esta caido, conectarse puede quedarse colgado.
# Este limite existe para que la tarea de fondo no se quede esperando
# indefinidamente y ocupando un hilo del servicio.
TIMEOUT = 10.0

ASILO = 'Asilo de Ancianos "Cabeza de Algodón"'

MESES = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
)


def _fecha_en_palabras(fecha_solicitud: str) -> str:
    """
    Convierte la fecha de la base a algo que se lea como fecha y no como
    dato de sistema: de "2026-09-22 15:26:03" a "22 de septiembre de 2026".

    Si por alguna razon la fecha no viene en el formato esperado, se
    devuelve tal cual: un correo con la fecha fea es mejor que ningun
    correo.
    """
    try:
        fecha = datetime.strptime(fecha_solicitud, "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return str(fecha_solicitud)
    return f"{fecha.day} de {MESES[fecha.month - 1]} de {fecha.year}"


def _cuerpo_texto(solicitud: dict, fecha: str) -> str:
    """
    Version en texto plano del aviso.

    Va dirigido al familiar, que no conoce el sistema ni sus terminos:
    aqui no se habla de "solicitudes", "estados" ni "registros", se habla
    de que a su pariente lo va a ver un especialista.
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

    Deliberadamente sobrio: sin imagenes, sin tipografias ni hojas de
    estilo traidas de internet. Un correo institucional debe verse igual
    y completo aunque el lector tenga bloqueado el contenido externo, que
    es como llegan por omision a la mayoria de bandejas.

    Los estilos van escritos dentro de cada etiqueta y no en un bloque
    <style> porque varios lectores de correo descartan ese bloque.

    El motivo y los nombres los escribe el personal en texto libre, asi
    que se escapan antes de entrar al HTML: si alguien escribe un signo
    "<" en el motivo, el correo no debe romperse.
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

    Recibe la fila completa de la solicitud, tal como la devolvio el
    repositorio, para no tener que consultar la base otra vez desde la
    tarea de fondo.

    No devuelve nada ni levanta excepciones a proposito: corre despues de
    que el medico ya recibio su confirmacion, cuando ya no hay a quien
    avisarle de un error mas que al log del contenedor.
    """
    destinatario = (solicitud.get("familiar_email") or "").strip()

    # Un interno sin familiar registrado es un caso normal, no un error:
    # hay quienes no tienen a nadie o nunca dejaron un correo. Se anota
    # para que quede constancia de POR QUE no salio el aviso, y se sigue.
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
        # El texto plano se pone primero y el HTML como alternativa: asi
        # lo pide el estandar, y quien lea el correo en un lector que no
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
    # El except es amplio a proposito. Aqui caben desde el servidor de
    # correo apagado hasta una direccion que el servidor rechaza, y
    # ninguno de esos casos justifica perder la remision, que a estas
    # alturas ya esta guardada en la base. Se anota el error con el numero
    # de remision para poder reenviar el aviso a mano si hiciera falta.
    except Exception as error:
        print(
            f"[ms-solicitudes] No se pudo enviar el aviso de la remision "
            f"{solicitud['id']} a {destinatario}: {error}",
            flush=True,
        )
