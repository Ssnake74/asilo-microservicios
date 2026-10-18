"""
Lectura de los demas microservicios.

ms-reportes no tiene esquema propio: cada informe se arma con lo que
devuelven los servicios que son duenos de esos datos. Asi un informe
nunca contradice lo que muestra la pantalla del modulo.

Solo lee. Si un servicio que hace falta no responde, el informe no se
arma a medias: se dice que modulo falta.
"""

import os

import httpx

MS_PACIENTES_URL = os.getenv("MS_PACIENTES_URL", "http://ms-pacientes:8083")
MS_SOLICITUDES_URL = os.getenv("MS_SOLICITUDES_URL", "http://ms-solicitudes:8081")
MS_COBROS_URL = os.getenv("MS_COBROS_URL", "http://ms-cobros:8082")
MS_CLINICO_URL = os.getenv("MS_CLINICO_URL", "http://ms-clinico:8085")

TIMEOUT = 5.0


class NoDisponible(Exception):
    def __init__(self, modulo: str):
        super().__init__(modulo)
        self.modulo = modulo


def _leer(url: str, modulo: str, params: dict | None = None):
    limpios = {k: v for k, v in (params or {}).items() if v not in (None, "")}
    try:
        respuesta = httpx.get(url, params=limpios, timeout=TIMEOUT)
    except httpx.RequestError as error:
        raise NoDisponible(modulo) from error
    if respuesta.status_code == 404:
        return None
    if respuesta.status_code != 200:
        raise NoDisponible(modulo)
    return respuesta.json()


def internos() -> list[dict]:
    return _leer(f"{MS_PACIENTES_URL}/pacientes", "registro de internos") or []


def interno(codigo: str) -> dict | None:
    return _leer(f"{MS_PACIENTES_URL}/pacientes/{codigo}", "registro de internos")


def remisiones(paciente_id: str | None = None) -> list[dict]:
    return _leer(f"{MS_SOLICITUDES_URL}/solicitudes", "remisiones médicas", {"paciente_id": paciente_id}) or []


def visitas(paciente_id: str | None = None) -> list[dict]:
    return _leer(f"{MS_SOLICITUDES_URL}/visitas", "visitas médicas", {"paciente_id": paciente_id}) or []


def fichas(paciente_id: str | None = None) -> list[dict]:
    return _leer(f"{MS_CLINICO_URL}/fichas", "atención médica", {"paciente_id": paciente_id}) or []


def cargos(paciente_id: str | None = None) -> list[dict]:
    return _leer(f"{MS_COBROS_URL}/cargos", "cobros", {"paciente_id": paciente_id}) or []


def cuotas(paciente_id: str | None = None) -> list[dict]:
    return _leer(f"{MS_COBROS_URL}/cuotas", "cobros", {"paciente_id": paciente_id}) or []


def donaciones(desde: str | None, hasta: str | None) -> list[dict]:
    return _leer(f"{MS_COBROS_URL}/donaciones", "cobros", {"desde": desde, "hasta": hasta}) or []


def gastos(desde: str | None, hasta: str | None) -> list[dict]:
    return _leer(f"{MS_COBROS_URL}/gastos", "cobros", {"desde": desde, "hasta": hasta}) or []


def pagos_fundacion(desde: str | None, hasta: str | None) -> list[dict]:
    return _leer(f"{MS_COBROS_URL}/fundacion/pagos", "cobros", {"desde": desde, "hasta": hasta}) or []


def deuda_fundacion() -> dict:
    return _leer(f"{MS_COBROS_URL}/fundacion/deuda", "cobros") or {}
