"""
Bandeja de Mailpit, consultada por su API.

Las pruebas de RF-44 necesitan saber si un correo llego o no llego. Se
busca siempre por un dato unico de la corrida (el destinatario o el
nombre del interno de prueba), nunca por "el ultimo mensaje": la bandeja
puede tener correos reales que no son de las pruebas y que no se tocan.
"""

import time

import httpx

BASE = "http://mailpit:8025"


def _cliente() -> httpx.Client:
    return httpx.Client(base_url=BASE, timeout=10.0)


def total() -> int:
    with _cliente() as c:
        return int(c.get("/api/v1/messages", params={"limit": 1}).json().get("total", 0))


def buscar(consulta: str) -> list[dict]:
    with _cliente() as c:
        r = c.get("/api/v1/search", params={"query": consulta, "limit": 250})
        r.raise_for_status()
        return r.json().get("messages") or []


def mensaje(identificador: str) -> dict:
    with _cliente() as c:
        return c.get(f"/api/v1/message/{identificador}").json()


def esperar(consulta: str, segundos: float) -> list[dict]:
    """
    Espera a que aparezca algo que coincida con la consulta.

    El aviso se manda como tarea de fondo DESPUES de responder al medico,
    asi que no esta en la bandeja en el instante en que vuelve el 201.
    """
    limite = time.time() + segundos
    while True:
        encontrados = buscar(consulta)
        if encontrados or time.time() >= limite:
            return encontrados
        time.sleep(0.5)


def borrar(identificadores: list[str]) -> None:
    if not identificadores:
        return
    with _cliente() as c:
        r = c.request("DELETE", "/api/v1/messages", json={"IDs": identificadores})
        r.raise_for_status()


def responde() -> bool:
    try:
        with httpx.Client(base_url=BASE, timeout=3.0) as c:
            return c.get("/api/v1/info").status_code == 200
    except httpx.HTTPError:
        return False
