from decimal import ROUND_HALF_UP, Decimal

# Dos decimales: los centavos del quetzal.
CENTAVOS = Decimal("0.01")


def a_decimal(valor) -> Decimal:
    return Decimal(str(valor))


def redondear(valor: Decimal) -> Decimal:
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
