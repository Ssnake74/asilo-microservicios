"""
Lo que comparten todos los grupos de pruebas durante una corrida.

Aqui viven:

  - las conexiones (gateway, Docker, MySQL como root),
  - la MARCA de la corrida, que va escrita en todo dato que se crea,
  - el registro de lo creado, para poder borrarlo al final,
  - la foto del sistema al empezar, para dejarlo exactamente igual,
  - funciones para crear internos, remisiones, tarifas y cargos de prueba
    sin repetir el mismo diccionario en cada grupo.

La marca existe para que los datos de prueba se reconozcan a simple vista
en cualquier pantalla o tabla ("PRUEBA-AUTO 20261008-154210") y para que
la limpieza pueda encontrarlos aunque la corrida se haya cortado a la
mitad y el registro en memoria se haya perdido.
"""

import os
import time
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

from .base_datos import Root
from .docker import CONTENEDORES, Docker
from .gateway import Gateway, resumen
from .reporte import Reporte

# Guatemala no tiene horario de verano: un desfase fijo es exacto y no
# depende de que la imagen traiga la base de zonas horarias.
GUATEMALA = timezone(timedelta(hours=-6))

PREFIJO_MARCA = "PRUEBA-AUTO"

MESES = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
)

CENTAVOS = Decimal("0.01")


def dinero(valor) -> Decimal:
    """Convierte a Decimal pasando por texto, para no heredar el error del float."""
    return Decimal(str(valor)).quantize(CENTAVOS, rounding=ROUND_HALF_UP)


def montos_esperados(precio, cantidad: int, porcentaje, beneficiario: bool) -> dict[str, Decimal]:
    """
    RN-09 y RN-10 calculados por las pruebas, de forma independiente del
    sistema: precio por cantidad, menos el porcentaje de la fundacion si
    el interno es beneficiario, todo redondeado a centavos con redondeo
    comercial (la mitad sube).

    Si el sistema calcula distinto, el caso lo muestra; por eso esta
    cuenta NO se importa de ms-cobros/app/reglas.py.
    """
    bruto = (Decimal(str(precio)) * cantidad).quantize(CENTAVOS, rounding=ROUND_HALF_UP)
    pct = Decimal(str(porcentaje)) if beneficiario else Decimal("0")
    descuento = (bruto * pct / Decimal("100")).quantize(CENTAVOS, rounding=ROUND_HALF_UP)
    return {"bruto": bruto, "descuento": descuento, "neto": bruto - descuento}


def q(valor) -> str:
    return f"Q{dinero(valor):,.2f}"


def fecha_en_palabras(momento: datetime) -> str:
    return (
        f"{momento.day} de {MESES[momento.month - 1]} de {momento.year}, "
        f"{momento:%H:%M:%S} (hora de Guatemala)"
    )


def hace_anios(base: date, anios: int) -> date:
    """La misma fecha N anios atras; el 29 de febrero cae al 28."""
    try:
        return base.replace(year=base.year - anios)
    except ValueError:
        return base.replace(year=base.year - anios, day=28)


class Contexto:
    def __init__(self):
        self.rep = Reporte()
        self.docker = Docker()

        mysql = self.docker.variables("asilo-mysql")
        self.root = Root(mysql.get("MYSQL_ROOT_PASSWORD", ""))

        self.contrasena = os.getenv("CONTRASENA_DEMO", "asilo2026")
        self.gw = Gateway(self.contrasena)

        self.red = os.getenv("RED_COMPOSE") or next(iter(self.docker.redes("asilo-gateway")), "")

        self.momento = datetime.now(GUATEMALA)
        self.hoy = self.momento.date()
        # Sello sin separadores: cabe en campos cortos (DPI, paciente_id).
        self.sello = self.momento.strftime("%Y%m%d%H%M%S")
        self.marca = f"{PREFIJO_MARCA} {self.momento:%Y%m%d-%H%M%S}"

        # Hora de inicio segun MySQL, que es el reloj con que la bitacora
        # anota sus filas. Comparar contra el reloj de este contenedor
        # podria dejar fuera una fila por un segundo de diferencia.
        self.inicio_sql = self.root.uno("SELECT DATE_FORMAT(NOW(), '%Y-%m-%d %H:%i:%s')")
        self.inicio_unix = int(time.time()) - 2

        # Lo que crea la corrida. La limpieza borra esto y ademas barre
        # por la marca, por si algo se creo sin que quedara anotado.
        self.creados: dict[str, list] = {
            "pacientes": [],
            "solicitudes": [],
            "visitas": [],
            "tarifas": [],
            "cargos": [],
            "correos": [],
        }

        self.inicial = self.fotografiar()

    # ------------------------------------------------------------------
    # Foto del sistema al empezar
    # ------------------------------------------------------------------

    def fotografiar(self) -> dict:
        return {
            "contenedores": {n: self.docker.estado(n) for n in CONTENEDORES},
            "contadores": self.root.contadores(),
            "max_bitacora": self.root.uno("SELECT COALESCE(MAX(id), 0) FROM asilo_gateway.bitacora"),
            "max_intentos": self.root.uno(
                "SELECT COALESCE(MAX(id), 0) FROM asilo_gateway.intentos_fallidos"
            ),
            "filas_bitacora": self.root.uno("SELECT COUNT(*) FROM asilo_gateway.bitacora"),
            "intentos": self.root.uno("SELECT COUNT(*) FROM asilo_gateway.intentos_fallidos"),
            "alias_correo": (self.docker.redes("asilo-mailpit").get(self.red) or {}).get("Aliases")
            or ["asilo-mailpit", "mailpit"],
        }

    # ------------------------------------------------------------------
    # Internos
    # ------------------------------------------------------------------

    def ficha_interno(self, etiqueta: str, **cambios) -> dict:
        """
        Ficha valida de un interno de prueba. Los apellidos llevan la
        marca: es el campo por el que la limpieza los encuentra.
        """
        ficha = {
            "nombres": "Prueba",
            "apellidos": f"{self.marca} {etiqueta}",
            "dpi": None,
            "fecha_nacimiento": "1950-05-20",
            "sexo": "F",
            "tipo_sangre": "O+",
            "fecha_ingreso": self.hoy.isoformat(),
            "habitacion": None,
            "procedencia": "Mazatenango",
            "familiar_nombre": "Familiar de prueba",
            "familiar_parentesco": "Hija",
            "familiar_telefono": "55550000",
            "familiar_email": None,
            "padecimientos": None,
            "alergias": None,
            "cubierto_fundacion": True,
        }
        ficha.update(cambios)
        return ficha

    def crear_interno(self, etiqueta: str, rol: str = "SECRETARIA", **cambios):
        ficha = self.ficha_interno(etiqueta, **cambios)
        r = self.gw.post(rol, "/api/pacientes", json=ficha)
        if r.status_code == 201:
            self.creados["pacientes"].append(r.json()["codigo"])
        return r, ficha

    def interno(self, etiqueta: str, **cambios) -> dict:
        """Crea un interno que la prueba NECESITA; si no se puede, la prueba no sigue."""
        r, _ = self.crear_interno(etiqueta, **cambios)
        if r.status_code != 201:
            raise RuntimeError(f"no se pudo crear el interno de apoyo: {resumen(r)}")
        return r.json()

    # ------------------------------------------------------------------
    # Remisiones y visitas
    # ------------------------------------------------------------------

    def crear_remision(self, paciente: dict, especialidad: str, correo: str | None = None,
                       etiqueta: str = "", rol: str = "MEDICO_GENERAL"):
        cuerpo = {
            "paciente_id": paciente["codigo"],
            "paciente_nombre": f"{paciente['nombres']} {paciente['apellidos']}"[:120],
            "familiar_email": correo,
            "medico_general": "Dr. Luis Marroquín",
            "especialidad_remitida": especialidad,
            "motivo": f"{self.marca}: remisión de prueba {etiqueta}".strip(),
            "cubierto_fundacion": paciente.get("cubierto_fundacion", True),
        }
        r = self.gw.post(rol, "/api/solicitudes", json=cuerpo)
        if r.status_code == 201:
            self.creados["solicitudes"].append(r.json()["id"])
        if correo:
            self.creados["correos"].append(correo)
        return r

    def remision(self, paciente: dict, especialidad: str, **kw) -> dict:
        r = self.crear_remision(paciente, especialidad, **kw)
        if r.status_code != 201:
            raise RuntimeError(f"no se pudo crear la remisión de apoyo: {resumen(r)}")
        return r.json()

    def convertir(self, solicitud_id: int, especialidad: str, fecha: str = "2026-12-01 09:30",
                  medico: str = "Dra. Prueba Automática", rol: str = "FUNDACION"):
        r = self.gw.post(
            rol,
            f"/api/solicitudes/{solicitud_id}/convertir",
            json={"medico_tratante": medico, "especialidad": especialidad, "fecha_visita": fecha},
        )
        if r.status_code == 201:
            visita = r.json()["visita"]
            self.creados["visitas"].append(visita["id"])
            if visita.get("cargo_id"):
                self.creados["cargos"].append(visita["cargo_id"])
        return r

    # ------------------------------------------------------------------
    # Tarifas y cargos
    # ------------------------------------------------------------------

    def crear_tarifa(self, etiqueta: str, tipo: str, precio, descuento, rol: str = "CAJA"):
        r = self.gw.post(
            rol,
            "/api/tarifas",
            json={
                "concepto": f"{self.marca} {etiqueta}"[:120],
                "tipo": tipo,
                "precio": precio,
                "descuento_fundacion": descuento,
                "activo": True,
            },
        )
        if r.status_code == 201:
            self.creados["tarifas"].append(r.json()["id"])
        return r

    def tarifa(self, etiqueta: str, tipo: str, precio, descuento) -> dict:
        r = self.crear_tarifa(etiqueta, tipo, precio, descuento)
        if r.status_code != 201:
            raise RuntimeError(f"no se pudo crear la tarifa de apoyo: {resumen(r)}")
        return r.json()

    def cuenta_de_prueba(self, sufijo: str) -> str:
        """Identificador de una cuenta de cobro de prueba (maximo 40 caracteres)."""
        return f"{PREFIJO_MARCA}-{self.sello}-{sufijo}"[:40]

    def crear_cargo(self, cuenta: str, tarifa: dict, cantidad: int = 1,
                    beneficiario: bool = True, rol: str = "CAJA"):
        r = self.gw.post(
            rol,
            "/api/cargos",
            json={
                "paciente_id": cuenta,
                "paciente_nombre": f"{self.marca} cuenta de prueba",
                "familiar_email": None,
                "tipo": tarifa["tipo"],
                "tarifa_id": tarifa["id"],
                "cantidad": cantidad,
                "cubierto_fundacion": beneficiario,
                "referencia": PREFIJO_MARCA,
            },
        )
        if r.status_code == 201:
            self.creados["cargos"].append(r.json()["id"])
        return r
