from typing import Literal, Optional

from pydantic import BaseModel, Field

TipoCargo = Literal["CITA", "EXAMEN", "MEDICAMENTO"]


class TarifaBase(BaseModel):
    concepto: str = Field(min_length=3, max_length=120)
    tipo: TipoCargo
    precio: float = Field(gt=0, description="Precio en quetzales, sin descuento")
    descuento_fundacion: float = Field(
        default=0, ge=0, le=100,
        description="Porcentaje que cubre la fundacion para pacientes beneficiarios",
    )
    activo: bool = True


class TarifaCrear(TarifaBase):
    pass


class TarifaActualizar(BaseModel):
    concepto: Optional[str] = Field(default=None, min_length=3, max_length=120)
    tipo: Optional[TipoCargo] = None
    precio: Optional[float] = Field(default=None, gt=0)
    descuento_fundacion: Optional[float] = Field(default=None, ge=0, le=100)
    activo: Optional[bool] = None


class Tarifa(TarifaBase):
    id: int


class CargoCrear(BaseModel):
    paciente_id: str = Field(min_length=1, max_length=40)
    paciente_nombre: Optional[str] = None
    familiar_email: Optional[str] = None
    tipo: TipoCargo
    tarifa_id: Optional[int] = Field(
        default=None,
        description="Si no se envia, se toma la primera tarifa activa de ese tipo",
    )
    cantidad: int = Field(default=1, ge=1, le=100)
    cubierto_fundacion: bool = Field(
        default=False, description="Indica si el paciente es beneficiario de la fundacion"
    )
    referencia: Optional[str] = Field(
        default=None, description="Origen del cargo, por ejemplo VISITA-7"
    )


class Cargo(BaseModel):
    id: int
    paciente_id: str
    paciente_nombre: Optional[str]
    familiar_email: Optional[str]
    tarifa_id: int
    concepto: str
    tipo: TipoCargo
    cantidad: int
    monto_bruto: float
    descuento_aplicado: float
    monto_neto: float
    cubierto_fundacion: bool
    estado: str
    referencia: Optional[str]
    fecha: str


class EstadoCuenta(BaseModel):
    """Resumen de la cuenta que el familiar debe cancelar al asilo."""

    paciente_id: str
    paciente_nombre: Optional[str]
    familiar_email: Optional[str]
    cantidad_cargos: int
    total_bruto: float
    total_descuento_fundacion: float
    total_neto: float
    total_pagado: float
    saldo_pendiente: float
    cargos: list[Cargo]


# =====================================================================
# Entradas y salidas del asilo (RF-33 a RF-36)
# =====================================================================

# Quienes donan, segun el enunciado: empresas internacionales y
# nacionales, gobierno y personas particulares.
TipoDonante = Literal["EMPRESA_INTERNACIONAL", "EMPRESA_NACIONAL", "GOBIERNO", "PARTICULAR"]

CategoriaGasto = Literal[
    "LUZ", "AGUA", "TELEFONO_INTERNET", "ALIMENTACION", "LIMPIEZA",
    "MANTENIMIENTO", "SALARIOS", "OTROS",
]

# Tope por registro: evita que un cero de mas descuadre los informes.
MONTO_MAXIMO = 1_000_000


class DonacionCrear(BaseModel):
    origen: str = Field(min_length=3, max_length=120, description="Quien dona")
    tipo_donante: TipoDonante
    monto: float = Field(gt=0, le=MONTO_MAXIMO)
    fecha: Optional[str] = Field(default=None, description="AAAA-MM-DD; sin fecha es hoy")
    descripcion: Optional[str] = Field(default=None, max_length=300)


class Donacion(BaseModel):
    id: int
    origen: str
    tipo_donante: TipoDonante
    monto: float
    fecha: str
    descripcion: Optional[str]


class GastoCrear(BaseModel):
    categoria: CategoriaGasto
    monto: float = Field(gt=0, le=MONTO_MAXIMO)
    fecha: Optional[str] = None
    descripcion: str = Field(min_length=3, max_length=300)
    comprobante: Optional[str] = Field(default=None, max_length=60, description="Factura o recibo")


class Gasto(BaseModel):
    id: int
    categoria: CategoriaGasto
    monto: float
    fecha: str
    descripcion: str
    comprobante: Optional[str]


class InternoDeCuota(BaseModel):
    paciente_id: str = Field(min_length=1, max_length=40)
    paciente_nombre: str = Field(min_length=1, max_length=120)
    familiar_email: Optional[str] = None


class CuotaCrear(InternoDeCuota):
    periodo: str = Field(description="Mes de la cuota, AAAA-MM")
    monto: float = Field(gt=0, le=MONTO_MAXIMO)


class CuotasGenerar(BaseModel):
    """Las cuotas de un mes para varios internos a la vez, con el mismo monto."""

    periodo: str
    monto: float = Field(gt=0, le=MONTO_MAXIMO)
    internos: list[InternoDeCuota] = Field(min_length=1)


class Cuota(BaseModel):
    id: int
    paciente_id: str
    paciente_nombre: str
    familiar_email: Optional[str]
    periodo: str
    monto: float
    estado: str
    fecha_registro: str
    fecha_pago: Optional[str]


class CuotasGeneradas(BaseModel):
    creadas: int
    ya_existian: int
    cuotas: list[Cuota]


class PagoFundacionCrear(BaseModel):
    monto: float = Field(gt=0, le=MONTO_MAXIMO)
    fecha: Optional[str] = None
    descripcion: Optional[str] = Field(default=None, max_length=300)
    comprobante: Optional[str] = Field(default=None, max_length=60)


class PagoFundacion(BaseModel):
    id: int
    monto: float
    fecha: str
    descripcion: Optional[str]
    comprobante: Optional[str]


class DeudaFundacion(BaseModel):
    """
    Lo que el asilo le debe a la fundacion (RF-36): lo que costaron sus
    consultas, examenes y medicamentos despues de su descuento, menos lo
    que ya se le pago.
    """

    total_servicios: float
    consultas: float
    examenes: float
    medicamentos: float
    total_pagado: float
    saldo: float
    citas_por_cobrar: int
