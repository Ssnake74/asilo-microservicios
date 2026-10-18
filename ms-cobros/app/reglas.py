# El calculo va en Decimal (RNF-15): con float, 0.1 + 0.2 da
# 0.30000000000000004 y los saldos dejan de cuadrar.

import re
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

# Dos decimales: los centavos del quetzal.
CENTAVOS = Decimal("0.01")


def a_decimal(valor) -> Decimal:
    # Pasa por str(): Decimal(0.1) hereda el error del float.
    return Decimal(str(valor))


def redondear(valor: Decimal) -> Decimal:
    # ROUND_HALF_UP: el medio centavo siempre sube. Por defecto Decimal
    # redondea al par y 0.125 daria 0.12.
    return valor.quantize(CENTAVOS, rounding=ROUND_HALF_UP)


def calcular_montos(
    precio,
    cantidad: int,
    descuento_fundacion,
    cubierto_fundacion: bool,
) -> dict[str, Decimal]:
    precio = a_decimal(precio)
    porcentaje = a_decimal(descuento_fundacion) if cubierto_fundacion else Decimal("0")

    monto_bruto = redondear(precio * cantidad)
    descuento_aplicado = redondear(monto_bruto * porcentaje / Decimal("100"))
    monto_neto = redondear(monto_bruto - descuento_aplicado)

    return {
        "monto_bruto": monto_bruto,
        "descuento_aplicado": descuento_aplicado,
        "monto_neto": monto_neto,
    }


# ---------------------------------------------------------------------
# Fechas y periodos de las entradas y salidas del asilo
# ---------------------------------------------------------------------

FORMA_PERIODO = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def fecha_valida(texto: str | None, hoy: date | None = None) -> date:
    """
    La fecha de una donacion, un gasto o un pago. Sin fecha es hoy; no se
    acepta una fecha futura, porque registra algo que ya ocurrio.
    """
    hoy = hoy or date.today()
    if not texto:
        return hoy
    try:
        fecha = datetime.strptime(texto.strip(), "%Y-%m-%d").date()
    except ValueError:
        raise ValueError("La fecha debe escribirse como AAAA-MM-DD, por ejemplo 2026-10-15.")
    if fecha > hoy:
        raise ValueError("La fecha no puede ser posterior a hoy.")
    return fecha


def periodo_valido(texto: str) -> str:
    """El mes de una cuota, como 2026-10."""
    limpio = (texto or "").strip()
    if not FORMA_PERIODO.match(limpio):
        raise ValueError("El mes de la cuota debe escribirse como AAAA-MM, por ejemplo 2026-10.")
    return limpio


def saldo_con_la_fundacion(total_servicios, total_pagado) -> Decimal:
    """Lo que el asilo todavia le debe a la fundacion, en Decimal (RNF-15)."""
    return redondear(a_decimal(total_servicios) - a_decimal(total_pagado))
