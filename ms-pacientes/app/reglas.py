"""
Reglas de negocio del microservicio de Pacientes.

Se mantienen fuera de main.py (la API) y de db.py (los datos), igual
que reglas.py en ms-cobros. Son funciones puras: reciben datos, calculan
y devuelven. No tocan la base ni saben que existe HTTP, y por eso se
pueden probar solas.
"""

from datetime import date, datetime


def calcular_edad(fecha_nacimiento: str, hoy: date | None = None) -> int:
    """
    Calcula la edad cumplida a partir de una fecha AAAA-MM-DD.

    La resta de anios sola no basta: si el cumpleanios todavia no llega
    este anio, hay que restar uno. Esa es la comparacion de la tupla
    (mes, dia).

    El parametro 'hoy' existe para poder probar la funcion con una fecha
    fija en vez de depender del dia en que se corra la prueba.
    """
    nacimiento = datetime.strptime(fecha_nacimiento, "%Y-%m-%d").date()
    referencia = hoy or date.today()
    return referencia.year - nacimiento.year - (
        (referencia.month, referencia.day) < (nacimiento.month, nacimiento.day)
    )


def ingreso_es_coherente(fecha_nacimiento: str, fecha_ingreso: str) -> bool:
    """Nadie puede ingresar al asilo antes de haber nacido."""
    return fecha_ingreso >= fecha_nacimiento
