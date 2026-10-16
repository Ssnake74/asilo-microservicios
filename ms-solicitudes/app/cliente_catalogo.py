"""
Consultas al microservicio de Catalogo.

La remision y la visita guardan el identificador de la especialidad, el
medico y el enfermero, y tambien su nombre: el nombre es el que se lee en
pantalla y en el correo, y asi la lista de visitas no depende de que el
catalogo responda.

A diferencia de cobros, aqui un catalogo caido SI detiene la operacion:
sin el no hay forma de comprobar RN-05.
"""

import os

import httpx

MS_CATALOGO_URL = os.getenv("MS_CATALOGO_URL", "http://ms-catalogo:8084")
TIMEOUT = 2.0


class CatalogoNoDisponible(Exception):
    """El catalogo no respondio."""


def _obtener(lista: str, registro_id: int) -> dict | None:
    """Devuelve el registro, o None si no existe."""
    try:
        respuesta = httpx.get(f"{MS_CATALOGO_URL}/catalogo/{lista}/{registro_id}", timeout=TIMEOUT)
    except httpx.RequestError as error:
        raise CatalogoNoDisponible() from error
    if respuesta.status_code == 404:
        return None
    if respuesta.status_code != 200:
        raise CatalogoNoDisponible()
    return respuesta.json()


def obtener_especialidad(especialidad_id: int) -> dict | None:
    return _obtener("especialidades", especialidad_id)


def obtener_medico(medico_id: int) -> dict | None:
    return _obtener("medicos", medico_id)


def obtener_enfermero(enfermero_id: int) -> dict | None:
    return _obtener("enfermeros", enfermero_id)
