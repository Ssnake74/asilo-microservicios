"""Modelos de entrada y salida del microservicio de Solicitudes."""

from typing import Optional

from pydantic import BaseModel, EmailStr, Field, model_validator


class SolicitudCrear(BaseModel):
    paciente_id: str = Field(min_length=1, max_length=40)
    paciente_nombre: str = Field(min_length=3, max_length=120)
    familiar_email: Optional[EmailStr] = Field(
        default=None, description="Correo al que se notifica la solicitud"
    )
    medico_general: str = Field(min_length=3, max_length=120)
    especialidad_id: Optional[int] = Field(
        default=None, description="Especialidad del catalogo a la que se remite al paciente",
    )
    especialidad_remitida: Optional[str] = Field(
        default=None, min_length=3, max_length=60,
        description="Especialidad escrita a mano; solo se usa si no se envia especialidad_id",
    )
    motivo: str = Field(min_length=5, max_length=400)
    cubierto_fundacion: bool = Field(
        default=True, description="El paciente recibe el descuento de la fundacion"
    )

    @model_validator(mode="after")
    def exige_especialidad(self):
        if self.especialidad_id is None and not self.especialidad_remitida:
            raise ValueError("Indique la especialidad a la que se remite al interno.")
        return self


class Solicitud(BaseModel):
    id: int
    paciente_id: str
    paciente_nombre: str
    familiar_email: Optional[str]
    medico_general: str
    especialidad_remitida: str
    especialidad_id: Optional[int]
    motivo: str
    cubierto_fundacion: bool
    estado: str
    fecha_solicitud: str


class ConversionSolicitud(BaseModel):
    """
    Datos que la fundacion agrega al asignar la visita medica formal.

    Lo normal es elegir medico y enfermero del catalogo (medico_id y
    enfermero_id). medico_tratante y especialidad escritos a mano se
    siguen aceptando cuando no se envia medico_id.
    """

    medico_id: Optional[int] = None
    enfermero_id: Optional[int] = None
    medico_tratante: Optional[str] = Field(default=None, min_length=3, max_length=120)
    especialidad: Optional[str] = Field(default=None, min_length=3, max_length=60)
    fecha_visita: str = Field(
        min_length=8, max_length=25, description="Fecha y hora asignada, formato AAAA-MM-DD HH:MM"
    )
    observaciones: Optional[str] = Field(default=None, max_length=400)


class Visita(BaseModel):
    id: int
    solicitud_id: int
    paciente_id: str
    paciente_nombre: str
    medico_id: Optional[int]
    medico_tratante: str
    especialidad: str
    enfermero_id: Optional[int]
    enfermero: Optional[str]
    fecha_visita: str
    observaciones: Optional[str]
    cargo_id: Optional[int]
    cargo_generado: bool
    # De la remision que origino la visita: quien remitio y por que.
    medico_general: Optional[str] = None
    motivo: Optional[str] = None


class VisitaCreada(BaseModel):
    """Respuesta de la conversion: la visita y el aviso del cobro asociado."""

    visita: Visita
    solicitud: Solicitud
    mensaje_cobro: str
