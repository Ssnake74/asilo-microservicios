"""
Reglas de negocio del microservicio de Solicitudes.

Se mantienen fuera de main.py (la API) y de db.py (los datos), igual que
en ms-pacientes y ms-cobros. Son funciones puras: reciben datos,
calculan y devuelven. No tocan la base ni saben que existe HTTP, y por
eso se pueden probar solas.

Estas funciones aparecieron con la migracion a MySQL. En SQLite la
fecha de la visita se guardaba como texto y cualquier cosa entraba;
MySQL tiene una columna DATETIME de verdad y rechaza lo que no sea una
fecha valida. Validar aqui permite responder un 422 con un mensaje
entendible en vez de dejar que reviente la capa de datos con un 500.
"""

from datetime import datetime

# Formatos que se aceptan al asignar la visita medica.
# El primero es el que escribe la aplicacion base; el segundo es el que
# produce un <input type="datetime-local"> del navegador; el tercero es
# para cuando solo se asigna el dia, sin hora.
FORMATOS_FECHA = ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d")


def normalizar_especialidad(texto: str) -> str:
    """
    Deja la especialidad siempre escrita igual: sin espacios sobrantes y
    con la primera letra de cada palabra en mayuscula.

    Sirve para que "cardiologia", " Cardiologia " y "CARDIOLOGIA" se
    guarden como "Cardiologia" y se puedan comparar entre si.
    """
    return texto.strip().title()


def especialidades_coinciden(remitida: str, asignada: str) -> bool:
    """
    Regla del documento de Estructura de Capas: la especialidad del
    medico tratante debe ser la misma a la que remitio el medico
    general. No se compara el texto crudo, sino el ya normalizado.
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
        f"por ejemplo 2026-09-15 09:30. Se recibio: {texto}"
    )
