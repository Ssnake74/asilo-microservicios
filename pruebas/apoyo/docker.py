"""
Acceso al motor de Docker desde dentro del contenedor de pruebas.

Se habla con el motor por su socket (/var/run/docker.sock), que
ejecutar.ps1 monta en el contenedor. Asi no hace falta instalar el
cliente de Docker en la imagen: la API del motor es HTTP comun.

Lo usan las pruebas que necesitan apagar un modulo (ms-cobros), congelar
o desconectar el servidor de correo, y leer los registros de un
microservicio para comprobar que una peticion nunca le llego.
"""

import time

import httpx

# Los siete contenedores del docker-compose.yml.
CONTENEDORES = (
    "asilo-mysql",
    "asilo-mailpit",
    "asilo-adminer",
    "asilo-ms-cobros",
    "asilo-ms-solicitudes",
    "asilo-ms-pacientes",
    "asilo-gateway",
)


class Docker:
    def __init__(self):
        self.cliente = httpx.Client(
            transport=httpx.HTTPTransport(uds="/var/run/docker.sock"),
            base_url="http://docker",
            timeout=60.0,
        )

    def version(self) -> dict:
        return self.cliente.get("/version").json()

    def inspeccionar(self, nombre: str) -> dict | None:
        r = self.cliente.get(f"/containers/{nombre}/json")
        return r.json() if r.status_code == 200 else None

    def estado(self, nombre: str) -> str:
        """running, paused, exited... o 'no existe'."""
        datos = self.inspeccionar(nombre)
        return datos["State"]["Status"] if datos else "no existe"

    def salud(self, nombre: str) -> str | None:
        datos = self.inspeccionar(nombre)
        if not datos:
            return None
        return (datos["State"].get("Health") or {}).get("Status")

    def variables(self, nombre: str) -> dict[str, str]:
        datos = self.inspeccionar(nombre) or {}
        resultado = {}
        for par in (datos.get("Config") or {}).get("Env") or []:
            clave, _, valor = par.partition("=")
            resultado[clave] = valor
        return resultado

    def puertos_publicados(self, nombre: str) -> dict:
        datos = self.inspeccionar(nombre) or {}
        return (datos.get("HostConfig") or {}).get("PortBindings") or {}

    def redes(self, nombre: str) -> dict:
        datos = self.inspeccionar(nombre) or {}
        return (datos.get("NetworkSettings") or {}).get("Networks") or {}

    # --------------------------------------------------- cambiar estado

    def _accion(self, nombre: str, accion: str, **params) -> None:
        r = self.cliente.post(f"/containers/{nombre}/{accion}", params=params)
        # 304 = ya estaba en ese estado; no es un error.
        if r.status_code not in (204, 304):
            raise RuntimeError(f"docker {accion} {nombre}: {r.status_code} {r.text.strip()}")

    def detener(self, nombre: str) -> None:
        self._accion(nombre, "stop", t=10)

    def iniciar(self, nombre: str) -> None:
        self._accion(nombre, "start")

    def pausar(self, nombre: str) -> None:
        self._accion(nombre, "pause")

    def reanudar(self, nombre: str) -> None:
        self._accion(nombre, "unpause")

    def desconectar(self, red: str, nombre: str) -> None:
        r = self.cliente.post(f"/networks/{red}/disconnect", json={"Container": nombre})
        if r.status_code != 200:
            raise RuntimeError(f"docker network disconnect: {r.status_code} {r.text.strip()}")

    def conectar(self, red: str, nombre: str, alias: list[str]) -> None:
        """
        Reconecta con los MISMOS alias que tenia. Sin ellos el contenedor
        vuelve a la red pero el nombre "mailpit" ya no lo encuentra nadie.
        """
        r = self.cliente.post(
            f"/networks/{red}/connect",
            json={"Container": nombre, "EndpointConfig": {"Aliases": alias}},
        )
        if r.status_code != 200:
            raise RuntimeError(f"docker network connect: {r.status_code} {r.text.strip()}")

    def esperar_estado(self, nombre: str, estado: str, segundos: float = 30) -> bool:
        limite = time.time() + segundos
        while time.time() < limite:
            if self.estado(nombre) == estado:
                return True
            time.sleep(0.5)
        return False

    # -------------------------------------------------------- registros

    def registros(self, nombre: str, desde: int) -> str:
        """
        Registros del contenedor desde una hora (segundos Unix).

        Sin terminal asignada, el motor entrega la salida en tramas: 8
        bytes de cabecera (el ultimo par dice cuanto mide la trama) y luego
        el texto. Hay que separarlas o el texto sale con basura intercalada.
        """
        r = self.cliente.get(
            f"/containers/{nombre}/logs",
            params={"stdout": 1, "stderr": 1, "since": desde},
        )
        crudo = r.content
        datos = self.inspeccionar(nombre) or {}
        if (datos.get("Config") or {}).get("Tty"):
            return crudo.decode("utf-8", errors="replace")

        partes = []
        i = 0
        while i + 8 <= len(crudo):
            largo = int.from_bytes(crudo[i + 4:i + 8], "big")
            partes.append(crudo[i + 8:i + 8 + largo])
            i += 8 + largo
        return b"".join(partes).decode("utf-8", errors="replace")
