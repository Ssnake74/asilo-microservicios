"""
Reglas de negocio del microservicio de Pacientes.

Funciones puras: no tocan la base ni saben que existe HTTP, y por eso
se pueden probar solas.
"""

from datetime import date, datetime


def calcular_edad(fecha_nacimiento: str, hoy: date | None = None) -> int:
    """
    Calcula la edad cumplida a partir de una fecha AAAA-MM-DD.

    Si el cumpleanios todavia no llega este anio se resta uno: esa es la
    comparacion de la tupla (mes, dia). 'hoy' permite probarla con una
    fecha fija.
    """
    nacimiento = datetime.strptime(fecha_nacimiento, "%Y-%m-%d").date()
    referencia = hoy or date.today()
    return referencia.year - nacimiento.year - (
        (referencia.month, referencia.day) < (nacimiento.month, nacimiento.day)
    )


def ingreso_es_coherente(fecha_nacimiento: str, fecha_ingreso: str) -> bool:
    """Nadie puede ingresar al asilo antes de haber nacido."""
    return fecha_ingreso >= fecha_nacimiento
