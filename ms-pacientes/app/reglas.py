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


def fecha_de_egreso(texto: str | None, fecha_ingreso: str, hoy: date | None = None) -> str:
    """
    La fecha en que el interno salio del asilo o fallecio (RF-13). Sin
    fecha es hoy. No puede ser futura ni anterior a su ingreso.
    """
    referencia = hoy or date.today()
    if not texto:
        return referencia.isoformat()
    try:
        fecha = datetime.strptime(texto.strip(), "%Y-%m-%d").date()
    except ValueError:
        raise ValueError("La fecha de egreso debe escribirse como AAAA-MM-DD, por ejemplo 2026-10-15.")
    if fecha > referencia:
        raise ValueError("La fecha de egreso no puede ser posterior a hoy.")
    if fecha.isoformat() < fecha_ingreso:
        raise ValueError("La fecha de egreso no puede ser anterior a la fecha de ingreso.")
    return fecha.isoformat()
