"""
Cliente HTTP del gateway, tal como lo veria el navegador.

Las pruebas hablan con el sistema por la misma puerta que las pantallas:
http://gateway:8080. Nunca le escriben directo a un microservicio, salvo
las contrapruebas de infraestructura que lo dicen expresamente.
"""

import http.client
import json as jsonlib

import httpx

BASE = "http://gateway:8080"

# Los cinco usuarios de demostracion que siembra el gateway (gateway/app/db.py).
USUARIO_DE_ROL = {
    "ADMIN": "admin",
    "SECRETARIA": "secretaria",
    "MEDICO_GENERAL": "medico",
    "FUNDACION": "fundacion",
    "CAJA": "caja",
}

# Como se llama cada rol en el ERS, para que el reporte use ese vocabulario.
NOMBRE_ROL = {
    "ADMIN": "Administrador",
    "SECRETARIA": "Secretaria",
    "MEDICO_GENERAL": "Médico general",
    "FUNDACION": "Fundación",
    "CAJA": "Caja",
}

ROLES = tuple(USUARIO_DE_ROL)


def detalle(respuesta) -> str | None:
    """
    El mensaje que devolvio el sistema, en una sola linea.

    Los errores de negocio traen {"detail": "texto"}. Los de validacion de
    FastAPI traen una lista; de esa se toman el campo y el mensaje de los
    dos primeros, que es lo que sirve para saber que se rechazo.
    """
    try:
        cuerpo = respuesta.json()
    except ValueError:
        texto = (respuesta.text or "").strip()
        return texto[:160] if texto else None

    if isinstance(cuerpo, dict) and "detail" in cuerpo:
        d = cuerpo["detail"]
        if isinstance(d, str):
            return d
        if isinstance(d, list) and d:
            partes = []
            for error in d[:2]:
                loc = error.get("loc") or ["?"]
                partes.append(f"{loc[-1]}: {error.get('msg')}")
            return "; ".join(partes)
    return None


def resumen(respuesta) -> str:
    """'422 · «mensaje»', o solo el codigo si no hay mensaje."""
    d = detalle(respuesta)
    return f"{respuesta.status_code} · «{d}»" if d else f"{respuesta.status_code}"


class RespuestaCruda:
    """Lo minimo para tratar una respuesta de http.client como una de httpx."""

    def __init__(self, status_code: int, cuerpo: bytes):
        self.status_code = status_code
        self.text = cuerpo.decode("utf-8", errors="replace")

    def json(self):
        return jsonlib.loads(self.text)


class Gateway:
    def __init__(self, contrasena: str):
        self.contrasena = contrasena
        self.cliente = httpx.Client(base_url=BASE, timeout=30.0)
        # Una sesion abierta por rol, reutilizada durante toda la corrida.
        self.sesion_de_rol: dict[str, str] = {}
        # Todos los testigos que abrio la corrida, para cerrarlos al final.
        self.testigos: set[str] = set()

    # ------------------------------------------------------------ basico

    def pedir(self, metodo: str, ruta: str, testigo: str | None = None,
              json=None, params=None, headers: dict | None = None) -> httpx.Response:
        """
        Una peticion con la sesion indicada, o sin sesion si testigo es None.

        La cookie se manda a mano y el frasco de cookies se vacia despues
        de cada peticion. Si se dejara que httpx las recordara, una prueba
        "sin sesion" podria viajar con la cookie que dejo la anterior y el
        resultado no significaria nada.
        """
        cabeceras = dict(headers or {})
        if testigo:
            cabeceras["Cookie"] = f"sesion={testigo}"
        try:
            return self.cliente.request(metodo, ruta, json=json, params=params, headers=cabeceras)
        finally:
            self.cliente.cookies.clear()

    def crudo(self, metodo: str, ruta: str, testigo: str | None = None,
              json=None, headers: dict | None = None) -> RespuestaCruda:
        """
        Peticion con la ruta EXACTA, sin que ninguna biblioteca la corrija.

        httpx normaliza las rutas (quita los "/../"), igual que lo haria un
        navegador. Para probar lo que pasa cuando alguien arma la peticion
        a mano, hace falta mandar la ruta tal cual: http.client no la toca.
        """
        conexion = http.client.HTTPConnection("gateway", 8080, timeout=30)
        cabeceras = dict(headers or {})
        cuerpo = None
        if json is not None:
            cuerpo = jsonlib.dumps(json).encode("utf-8")
            cabeceras["Content-Type"] = "application/json"
        if testigo:
            cabeceras["Cookie"] = f"sesion={testigo}"
        try:
            conexion.request(metodo, ruta, body=cuerpo, headers=cabeceras)
            r = conexion.getresponse()
            return RespuestaCruda(r.status, r.read())
        finally:
            conexion.close()

    # ----------------------------------------------------------- sesiones

    def ingresar(self, usuario: str, contrasena: str | None = None) -> httpx.Response:
        r = self.pedir(
            "POST", "/api/login",
            json={"usuario": usuario, "contrasena": self.contrasena if contrasena is None else contrasena},
        )
        if r.status_code == 200 and r.cookies.get("sesion"):
            self.testigos.add(r.cookies.get("sesion"))
        return r

    def testigo_de(self, respuesta: httpx.Response) -> str | None:
        return respuesta.cookies.get("sesion")

    def como(self, rol: str) -> str:
        """Testigo de sesion de ese rol; entra la primera vez que se pide."""
        if rol not in self.sesion_de_rol:
            r = self.ingresar(USUARIO_DE_ROL[rol])
            if r.status_code != 200:
                raise RuntimeError(
                    f"No se pudo entrar como {USUARIO_DE_ROL[rol]}: {resumen(r)}"
                )
            self.sesion_de_rol[rol] = self.testigo_de(r)
        return self.sesion_de_rol[rol]

    # ---------------------------------------------------- atajos por rol

    def get(self, rol: str | None, ruta: str, **kw) -> httpx.Response:
        return self.pedir("GET", ruta, self.como(rol) if rol else None, **kw)

    def post(self, rol: str | None, ruta: str, **kw) -> httpx.Response:
        return self.pedir("POST", ruta, self.como(rol) if rol else None, **kw)

    def put(self, rol: str | None, ruta: str, **kw) -> httpx.Response:
        return self.pedir("PUT", ruta, self.como(rol) if rol else None, **kw)

    def delete(self, rol: str | None, ruta: str, **kw) -> httpx.Response:
        return self.pedir("DELETE", ruta, self.como(rol) if rol else None, **kw)
