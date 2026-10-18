"""Modelos de entrada y salida del microservicio Clinico."""

from typing import Optional

from pydantic import BaseModel, Field


# ------------------------------------------------------------- entrada

class FichaCrear(BaseModel):
    visita_id: int
    diagnostico: str = Field(min_length=5, max_length=1000)
    observaciones: Optional[str] = Field(default=None, max_length=1000)


class OrdenCrear(BaseModel):
    ficha_id: int
    tipo_examen_id: int
    indicaciones: Optional[str] = Field(default=None, max_length=300)


class ResultadoCrear(BaseModel):
    orden_id: int
    resultado: str = Field(min_length=3, max_length=2000)


class RecetaCrear(BaseModel):
    ficha_id: int
    medicamento_id: int
    cantidad: int = Field(ge=1, le=100)
    # El tiempo de aplicacion que pide RF-24: «una tableta cada 8 horas por 5 dias».
    indicaciones: str = Field(min_length=5, max_length=300)


class DespachoCrear(BaseModel):
    receta_id: int
    cantidad: int = Field(ge=1, le=100)


# -------------------------------------------------------------- salida

class Resultado(BaseModel):
    resultado: str
    fecha_resultado: str
    responsable: Optional[str]


class Orden(BaseModel):
    id: int
    ficha_id: int
    visita_id: int
    paciente_id: str
    paciente_nombre: str
    especialidad: str
    medico: str
    tipo_examen_id: int
    examen: str
    indicaciones: Optional[str]
    estado: str
    fecha_orden: str
    cargo_id: Optional[int]
    cargo_generado: bool
    resultado: Optional[Resultado] = None


class Despacho(BaseModel):
    cantidad_despachada: int
    fecha: str
    responsable: Optional[str]
    cargo_id: Optional[int]
    cargo_generado: bool


class Receta(BaseModel):
    id: int
    ficha_id: int
    visita_id: int
    paciente_id: str
    paciente_nombre: str
    especialidad: str
    medico: str
    medicamento_id: int
    medicamento: str
    cantidad: int
    indicaciones: str
    estado: str
    fecha: str
    despacho: Optional[Despacho] = None


class Ficha(BaseModel):
    id: int
    visita_id: int
    paciente_id: str
    paciente_nombre: str
    especialidad: str
    medico: str
    fecha_visita: str
    diagnostico: str
    observaciones: Optional[str]
    fecha: str
    responsable: Optional[str]
    examenes: list[Orden] = []
    recetas: list[Receta] = []


class ConCobro(BaseModel):
    """Respuesta del resultado y del despacho: lo registrado y el aviso del cobro."""

    orden: Optional[Orden] = None
    receta: Optional[Receta] = None
    mensaje_cobro: str
