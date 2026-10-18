"""
Comunicacion con los otros microservicios.

  - ms-solicitudes: la visita que se atiende y los datos del interno.
  - ms-catalogo:    el examen o el medicamento, con su nombre y su precio.
  - ms-cobros:      el cargo del examen o del medicamento entregado (RF-29).

Las dos primeras se necesitan para registrar: si no responden, la
operacion no se puede hacer y se dice. El cobro no: si cobros no
responde, el resultado o el despacho quedan registrados igual y el cargo
pendiente (RNF-12), y main.py lo reintenta despues (RNF-13).
"""

import os
import socket
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as Agotado
from urllib.parse import urlsplit

import httpx

MS_SOLICITUDES_URL = os.getenv("MS_SOLICITUDES_URL", "http://ms-solicitudes:8081")
MS_CATALOGO_URL = os.getenv("MS_CATALOGO_URL", "http://ms-catalogo:8084")
MS_COBROS_URL = os.getenv("MS_COBROS_URL", "http://ms-cobros:8082")

# Corto, por la misma razon que en ms-solicitudes: el gateway corta a los 8 s.
TIMEOUT = 2.0


# ---------------------------------------------------------------------
# Antes de llamar a cobros se resuelve su nombre, con tope de tiempo.
#
# Con el contenedor de cobros apagado, el DNS de Docker tarda de 4 a 8
# segundos en contestar que ese nombre no existe, y esa espera no la
# cubre el TIMEOUT de httpx: solo cuenta desde que hay direccion. Sumada
# al resto, la respuesta llegaba al gateway despues de sus 8 segundos y el
# usuario veia un error por algo que si quedo guardado.
# ---------------------------------------------------------------------

_RESOLVEDOR = ThreadPoolExecutor(max_workers=2)

NO_RESPONDE = (
    "El servicio de cobros no respondió. Lo registrado quedó guardado y el "
    "cargo se generará solo cuando el servicio vuelva."
)


def cobros_alcanzable(segundos: float = TIMEOUT) -> bool:
    """True si el nombre de cobros se resuelve dentro del tope."""
    partes = urlsplit(MS_COBROS_URL)
    futuro = _RESOLVEDOR.submit(socket.getaddrinfo, partes.hostname, partes.port or 80)
    try:
        futuro.result(timeout=segundos)
        return True
    except (Agotado, OSError):
        return False


class NoDisponible(Exception):
    """Un servicio que hace falta para registrar no respondio."""

    def __init__(self, modulo: str):
        super().__init__(modulo)
        self.modulo = modulo


def _obtener(url: str, modulo: str) -> dict | None:
    """El registro, o None si el servicio responde que no existe."""
    try:
        respuesta = httpx.get(url, timeout=TIMEOUT)
    except httpx.RequestError as error:
        raise NoDisponible(modulo) from error
    if respuesta.status_code == 404:
        return None
    if respuesta.status_code != 200:
        raise NoDisponible(modulo)
    return respuesta.json()


def visita_con_su_remision(visita_id: int) -> dict | None:
    """
    La visita y, de su remision, el correo del familiar y si la fundacion
    cubre al interno: los cargos de examenes y medicamentos se calculan
    igual que el de la consulta.
    """
    visita = _obtener(f"{MS_SOLICITUDES_URL}/visitas/{visita_id}", "visitas médicas")
    if visita is None:
        return None
    solicitud = _obtener(f"{MS_SOLICITUDES_URL}/solicitudes/{visita['solicitud_id']}", "visitas médicas")
    visita["familiar_email"] = solicitud["familiar_email"] if solicitud else None
    visita["cubierto_fundacion"] = solicitud["cubierto_fundacion"] if solicitud else False
    return visita


def examen(tipo_examen_id: int) -> dict | None:
    return _obtener(f"{MS_CATALOGO_URL}/catalogo/examenes/{tipo_examen_id}", "catálogo médico")


def medicamento(medicamento_id: int) -> dict | None:
    return _obtener(f"{MS_CATALOGO_URL}/catalogo/medicamentos/{medicamento_id}", "catálogo médico")


def cobros_responde() -> bool:
    """Pregunta rapida antes de reintentar, para no esperar el limite por cada cargo."""
    if not cobros_alcanzable():
        return False
    try:
        return httpx.get(f"{MS_COBROS_URL}/health", timeout=TIMEOUT).status_code == 200
    except httpx.RequestError:
        return False


def generar_cargo(ficha: dict, tipo: str, tarifa_id: int | None, cantidad: int,
                  referencia: str, que: str) -> tuple[int | None, str]:
    """
    Pide a cobros el cargo y devuelve (id del cargo, mensaje). Si no se
    pudo, el id es None y el mensaje dice por que, para la pantalla.
    """
    if tarifa_id is None:
        return None, (
            f"{que} no tiene precio en el catálogo médico: no se generó cobro. "
            "La fundación puede asignarle uno en el catálogo."
        )
    if not cobros_alcanzable():
        return None, NO_RESPONDE
    cuerpo = {
        "paciente_id": ficha["paciente_id"],
        "paciente_nombre": ficha["paciente_nombre"],
        "familiar_email": ficha["familiar_email"],
        "tipo": tipo,
        "tarifa_id": tarifa_id,
        "cantidad": cantidad,
        "cubierto_fundacion": bool(ficha["cubierto_fundacion"]),
        "referencia": referencia,
    }
    try:
        respuesta = httpx.post(f"{MS_COBROS_URL}/cargos", json=cuerpo, timeout=TIMEOUT)
        respuesta.raise_for_status()
        cargo = respuesta.json()
    except httpx.HTTPStatusError as error:
        return None, (
            f"El servicio de cobros rechazó el cargo (código {error.response.status_code}). "
            "Lo registrado quedó guardado; el cargo se agrega desde Cuentas."
        )
    except httpx.RequestError:
        return None, NO_RESPONDE
    return cargo["id"], (
        f"Cargo {cargo['id']} generado por Q{cargo['monto_neto']:.2f} "
        f"(la fundación cubrió Q{cargo['descuento_aplicado']:.2f})."
    )
