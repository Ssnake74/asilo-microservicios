# El calculo va en Decimal (RNF-15): con float, 0.1 + 0.2 da
# 0.30000000000000004 y los saldos dejan de cuadrar.

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
