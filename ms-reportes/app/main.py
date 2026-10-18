"""
Microservicio de Reportes
Sistema para Administracion Asilo de Ancianos "Cabeza de Algodon"

Los siete informes del enunciado (RF-37 a RF-43). No tiene esquema
propio: lee de pacientes, solicitudes, clinico y cobros (clientes.py) y
arma cada informe con reglas.py. Capa de presentacion: solo las rutas y
la revision de los filtros.

Puerto: 8086
"""

from datetime import date, datetime

from fastapi import FastAPI, HTTPException, Query

from . import clientes, reglas
from .schemas import Informe

app = FastAPI(
    title="MS Reportes - Asilo Cabeza de Algodon",
    description="Informes de costos, atención médica, cobros, donaciones y pagos a la fundación.",
    version="1.0.0",
)

# Lo que la pantalla ofrece: clave, nombre, requisito y que filtros usa.
CATALOGO = [
    {"clave": "costos", "titulo": "Costos por cita y por interno", "requisito": "RF-37",
     "interno": "opcional", "fechas": True},
    {"clave": "analisis", "titulo": "Análisis médicos por interno", "requisito": "RF-38",
     "interno": "obligatorio", "fechas": False},
    {"clave": "cobros", "titulo": "Cobros por interno", "requisito": "RF-39",
     "interno": "obligatorio", "fechas": True},
    {"clave": "pagos-fundacion", "titulo": "Pagos realizados a la fundación", "requisito": "RF-40",
     "interno": "no", "fechas": True},
    {"clave": "ingresos", "titulo": "Ingresos por donaciones y cobros", "requisito": "RF-41",
     "interno": "no", "fechas": True},
    {"clave": "examenes", "titulo": "Exámenes realizados por interno", "requisito": "RF-42",
     "interno": "opcional", "fechas": True},
    {"clave": "medicamentos", "titulo": "Medicamentos aplicados por interno", "requisito": "RF-43",
     "interno": "opcional", "fechas": True},
]


def _fecha(texto: str | None, nombre: str) -> str | None:
    if not texto:
        return None
    try:
        return datetime.strptime(texto.strip(), "%Y-%m-%d").date().isoformat()
    except ValueError:
        raise HTTPException(status_code=422, detail=f"La fecha «{nombre}» debe escribirse como AAAA-MM-DD.")


def _rango(desde: str | None, hasta: str | None) -> tuple[str | None, str | None]:
    d, h = _fecha(desde, "desde"), _fecha(hasta, "hasta")
    if d and h and d > h:
        raise HTTPException(status_code=422, detail="La fecha inicial no puede ser posterior a la final.")
    return d, h


def _interno(paciente_id: str | None) -> dict:
    if not paciente_id:
        raise HTTPException(status_code=422, detail="Elija al interno del informe.")
    try:
        encontrado = clientes.interno(paciente_id)
    except clientes.NoDisponible as error:
        raise HTTPException(status_code=503, detail=f"El módulo de {error.modulo} no está disponible.")
    if encontrado is None:
        raise HTTPException(status_code=404, detail="No existe un interno con ese código.")
    return encontrado


def _texto_filtros(interno: dict | None, desde: str | None, hasta: str | None) -> str:
    partes = []
    if interno:
        partes.append(f"Interno: {interno['nombres']} {interno['apellidos']} ({interno['codigo']})")
    if desde and hasta:
        partes.append(f"Del {desde} al {hasta}")
    elif desde:
        partes.append(f"Desde el {desde}")
    elif hasta:
        partes.append(f"Hasta el {hasta}")
    return " · ".join(partes) or "Todos los registros"


def _armar(clave: str, construir, interno: dict | None = None,
           desde: str | None = None, hasta: str | None = None) -> dict:
    """Arma el informe; si un servicio no responde, 503 con el nombre del modulo."""
    try:
        informe = construir()
    except clientes.NoDisponible as error:
        raise HTTPException(
            status_code=503,
            detail=f"El módulo de {error.modulo} no está disponible: el informe no se puede armar ahora.",
        )
    informe["clave"] = clave
    informe["filtros"] = _texto_filtros(interno, desde, hasta)
    informe["generado"] = datetime.now().replace(microsecond=0).isoformat(sep=" ")
    return informe


def _por_codigo() -> dict:
    return {p["codigo"]: p for p in clientes.internos()}


# ---------------------------------------------------------------- rutas

@app.get("/health", tags=["Estado"])
def health() -> dict:
    return {"servicio": "ms-reportes", "estado": "arriba", "informes": len(CATALOGO), "hoy": date.today().isoformat()}


@app.get("/reportes", tags=["Informes"])
def catalogo() -> list[dict]:
    return CATALOGO


@app.get("/reportes/costos", response_model=Informe, tags=["Informes"])
def costos(paciente_id: str | None = None, desde: str | None = None, hasta: str | None = None):
    d, h = _rango(desde, hasta)
    interno = _interno(paciente_id) if paciente_id else None
    return _armar("costos", lambda: reglas.costos_por_cita(
        clientes.visitas(paciente_id), clientes.fichas(paciente_id), clientes.cargos(paciente_id),
        _por_codigo(), d, h), interno, d, h)


@app.get("/reportes/analisis", response_model=Informe, tags=["Informes"])
def analisis(paciente_id: str | None = Query(default=None)):
    interno = _interno(paciente_id)
    return _armar("analisis", lambda: reglas.analisis_medicos(
        interno, clientes.remisiones(paciente_id), clientes.visitas(paciente_id),
        clientes.fichas(paciente_id)), interno)


@app.get("/reportes/cobros", response_model=Informe, tags=["Informes"])
def cobros(paciente_id: str | None = None, desde: str | None = None, hasta: str | None = None):
    d, h = _rango(desde, hasta)
    interno = _interno(paciente_id)
    return _armar("cobros", lambda: reglas.cobros_por_interno(
        interno, clientes.cargos(paciente_id), clientes.cuotas(paciente_id), d, h), interno, d, h)


@app.get("/reportes/pagos-fundacion", response_model=Informe, tags=["Informes"])
def pagos_fundacion(desde: str | None = None, hasta: str | None = None):
    d, h = _rango(desde, hasta)
    return _armar("pagos-fundacion", lambda: reglas.pagos_a_la_fundacion(
        clientes.pagos_fundacion(d, h), clientes.deuda_fundacion()), None, d, h)


@app.get("/reportes/ingresos", response_model=Informe, tags=["Informes"])
def ingresos(desde: str | None = None, hasta: str | None = None):
    d, h = _rango(desde, hasta)
    return _armar("ingresos", lambda: reglas.ingresos(
        clientes.donaciones(d, h), clientes.cuotas(), clientes.cargos(), clientes.gastos(d, h),
        _por_codigo(), d, h), None, d, h)


@app.get("/reportes/examenes", response_model=Informe, tags=["Informes"])
def examenes(paciente_id: str | None = None, desde: str | None = None, hasta: str | None = None):
    d, h = _rango(desde, hasta)
    interno = _interno(paciente_id) if paciente_id else None
    return _armar("examenes", lambda: reglas.examenes_realizados(
        clientes.fichas(paciente_id), _por_codigo(), d, h), interno, d, h)


@app.get("/reportes/medicamentos", response_model=Informe, tags=["Informes"])
def medicamentos(paciente_id: str | None = None, desde: str | None = None, hasta: str | None = None):
    d, h = _rango(desde, hasta)
    interno = _interno(paciente_id) if paciente_id else None
    return _armar("medicamentos", lambda: reglas.medicamentos_aplicados(
        clientes.fichas(paciente_id), _por_codigo(), d, h), interno, d, h)
