"""
Historial del interno en los otros microservicios.

Las remisiones (y con ellas las visitas y la atencion medica) viven en
ms-solicitudes; los cobros y las cuotas, en ms-cobros. Guardan el codigo
del interno como referencia logica: el motor no puede impedir que se
borre la ficha porque las tablas estan en esquemas distintos. Por eso,
antes de eliminar una ficha, este modulo pregunta a esos servicios si el
interno tiene algo registrado.

Las tres consultas van en paralelo y con un tope comun. Si un servicio
no responde a tiempo, no se puede saber si hay historial y la ficha no
se elimina.
"""

import os
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as Agotado

import httpx

MS_SOLICITUDES_URL = os.getenv("MS_SOLICITUDES_URL", "http://ms-solicitudes:8081")
MS_COBROS_URL = os.getenv("MS_COBROS_URL", "http://ms-cobros:8082")

# Tope total. El gateway corta a los 8 s; el tope cubre tambien la espera
# del DNS cuando un contenedor esta apagado.
TOPE = 4.0

_HILOS = ThreadPoolExecutor(max_workers=3)


class NoDisponible(Exception):
    """Un servicio no respondio y no se puede comprobar el historial."""

    def __init__(self, modulo: str):
        super().__init__(modulo)
        self.modulo = modulo


def _contar(url: str, codigo: str, modulo: str) -> int:
    try:
        respuesta = httpx.get(url, params={"paciente_id": codigo}, timeout=TOPE)
    except httpx.RequestError as error:
        raise NoDisponible(modulo) from error
    if respuesta.status_code != 200:
        raise NoDisponible(modulo)
    return len(respuesta.json())


def _plural(cantidad: int, singular: str, plural: str) -> str:
    return f"{cantidad} {singular if cantidad == 1 else plural}"


def registros_del_interno(codigo: str) -> list[str]:
    """Lo que el interno tiene registrado fuera de su ficha, en palabras.

    Lista vacia si no tiene nada. NoDisponible si un servicio no respondio.
    """
    consultas = [
        (f"{MS_SOLICITUDES_URL}/solicitudes", "remisiones", ("remisión", "remisiones")),
        (f"{MS_COBROS_URL}/cargos", "cobros", ("cobro", "cobros")),
        (f"{MS_COBROS_URL}/cuotas", "cobros", ("cuota mensual", "cuotas mensuales")),
    ]
    futuros = [
        (_HILOS.submit(_contar, url, codigo, modulo), modulo, nombres)
        for url, modulo, nombres in consultas
    ]
    encontrados = []
    for futuro, modulo, (singular, plural) in futuros:
        try:
            cantidad = futuro.result(timeout=TOPE)
        except Agotado as error:
            raise NoDisponible(modulo) from error
        if cantidad:
            encontrados.append(_plural(cantidad, singular, plural))
    return encontrados
