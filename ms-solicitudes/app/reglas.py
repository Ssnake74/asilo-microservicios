"""
Reglas de negocio del microservicio de Solicitudes.

Funciones puras: no tocan la base ni saben que existe HTTP. Validar la
fecha aqui permite responder 422 con un mensaje entendible, en vez de
un 500 cuando MySQL la rechaza.
"""

from datetime import datetime

# Formatos que se aceptan al asignar la visita medica: el de la
# aplicacion base, el de un <input type="datetime-local">, el mismo con
# segundos y el del dia solo, sin hora.
FORMATOS_FECHA = ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d")


def normalizar_especialidad(texto: str) -> str:
    """
    Deja la especialidad siempre escrita igual: un solo espacio entre
    palabras y la primera letra de cada una en mayuscula.

    Sirve para que "cardiologia", " Cardiologia " y "medicina   interna"
    se guarden como "Cardiologia" y "Medicina Interna". Solo se usa
    cuando la especialidad llega escrita y no elegida del catalogo.
    """
    return " ".join(texto.split()).title()


def especialidades_coinciden(remitida: str, asignada: str) -> bool:
    """
    La especialidad del medico tratante debe ser la misma a la que
    remitio el medico general. Se compara el texto ya normalizado.
    """
    return normalizar_especialidad(remitida) == normalizar_especialidad(asignada)


def normalizar_fecha_visita(texto: str) -> datetime:
    """
    Convierte el texto de la fecha de la visita en un datetime.

    Lanza ValueError si el texto no corresponde a ninguno de los
    formatos aceptados; main.py atrapa ese error y responde 422 con un
    mensaje para el usuario, en vez de mandarle el texto malo a MySQL.
    """
    limpio = texto.strip()
    for formato in FORMATOS_FECHA:
        try:
            return datetime.strptime(limpio, formato)
        except ValueError:
            continue
    raise ValueError(
        "La fecha y hora de la visita debe escribirse como AAAA-MM-DD HH:MM, "
        f"por ejemplo 2026-09-15 09:30. Se recibió: {texto}"
    )
