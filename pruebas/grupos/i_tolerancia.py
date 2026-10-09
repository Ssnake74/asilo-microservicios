"""
I · Tolerancia a fallos (RNF-11, RNF-12, RNF-13)

Se apaga de verdad el contenedor de cobros (docker stop) y se comprueba
que el resto del sistema sigue atendiendo. Al final se vuelve a encender
y se espera a que responda antes de seguir con los demas grupos.

Si la corrida se corta mientras cobros esta apagado, el bloque final de
pruebas.py lo vuelve a encender, y ejecutar.ps1 lo revisa otra vez.
"""

import time

import httpx

from apoyo.gateway import resumen

LETRA = "I"
TITULO = "Tolerancia a fallos"
DESCRIPCION = (
    "Con el módulo de cobros apagado, las visitas se siguen programando y los "
    "demás módulos siguen atendiendo. Luego se enciende y se verifica la recuperación."
)

COBROS = "asilo-ms-cobros"


def esperar_cobros(segundos: float = 90) -> bool:
    """El contenedor arriba no basta: hay que esperar a que la API conteste."""
    limite = time.time() + segundos
    while time.time() < limite:
        try:
            if httpx.get("http://ms-cobros:8082/health", timeout=3).status_code == 200:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(1)
    return False


def ejecutar(ctx) -> None:
    rep, gw, docker = ctx.rep, ctx.gw, ctx.docker

    paciente = ctx.interno("I tolerancia")
    remision = ctx.remision(paciente, "Cardiologia", etiqueta="I sin cobros")
    visita_sin_cargo = None

    docker.detener(COBROS)
    apagado = docker.esperar_estado(COBROS, "exited", 30)
    rep.nota(
        f"Se detuvo {COBROS} (estado: {docker.estado(COBROS)}). "
        + ("" if apagado else "ATENCIÓN: no llegó a detenerse; los casos siguientes no son concluyentes.")
    )

    try:
        with rep.caso(
            "Programar una visita con el módulo de cobros apagado",
            "RNF-12",
            "201: la visita se registra igual, con cargo_generado falso, sin cargo, y "
            "con un aviso de que el cargo queda pendiente",
        ) as c:
            inicio = time.time()
            r = ctx.convertir(remision["id"], "Cardiologia")
            demora = time.time() - inicio
            if r.status_code == 201:
                datos = r.json()
                visita_sin_cargo = datos["visita"]
                c.obtenido = (
                    f"201 en {demora:.1f} s · visita {visita_sin_cargo['id']} · "
                    f"cargo_generado={visita_sin_cargo['cargo_generado']} · "
                    f"cargo_id={visita_sin_cargo['cargo_id']} · «{datos['mensaje_cobro']}»"
                )
                c.pasa = visita_sin_cargo["cargo_generado"] is False and visita_sin_cargo["cargo_id"] is None
            else:
                # Que la respuesta sea un error no dice si la visita se
                # guardo o no: el servicio puede haber terminado su trabajo
                # despues de que el gateway se canso de esperar. Se mira en
                # la base, que es lo que de verdad le importa al asilo.
                time.sleep(3)
                filas = ctx.root.consulta(
                    """SELECT id, cargo_generado, cargo_id FROM asilo_solicitudes.visitas
                       WHERE solicitud_id = %s""",
                    (remision["id"],),
                )
                estado = ctx.root.uno(
                    "SELECT estado FROM asilo_solicitudes.solicitudes WHERE id = %s", (remision["id"],)
                )
                c.obtenido = f"{resumen(r)} en {demora:.1f} s"
                if filas:
                    fila = filas[0]
                    ctx.creados["visitas"].append(fila["id"])
                    visita_sin_cargo = {"id": fila["id"]}
                    c.obtenido += (
                        f"\nSin embargo la visita SÍ quedó registrada: visita {fila['id']}, "
                        f"cargo_generado={bool(fila['cargo_generado'])}, remisión {estado}. "
                        "El usuario recibe un error por una operación que sí se hizo."
                    )
                else:
                    c.obtenido += f"\nLa visita no quedó registrada; remisión {estado}."

        with rep.caso(
            "Consultar cobros con el módulo apagado",
            "RNF-11",
            "503 del gateway con un mensaje entendible, no un 500",
        ) as c:
            r = gw.get("CAJA", "/api/cargos")
            c.obtenido = resumen(r)
            c.pasa = r.status_code == 503

        with rep.caso(
            "Los demás módulos siguen funcionando",
            "RNF-11",
            "Internos y remisiones responden con normalidad, se puede registrar un "
            "interno, y el tablero de estado marca solo a cobros como caído",
        ) as c:
            internos = gw.get("SECRETARIA", "/api/pacientes")
            remisiones = gw.get("FUNDACION", "/api/solicitudes")
            alta, _ = ctx.crear_interno("I alta durante la caida")
            salud = gw.get("ADMIN", "/api/salud").json()
            arriba = {k: v["arriba"] for k, v in salud.items()}
            c.obtenido = (
                f"internos: {internos.status_code} · remisiones: {remisiones.status_code} · "
                f"alta de interno: {alta.status_code} · tablero: "
                + ", ".join(f"{k} {'arriba' if v else 'caído'}" for k, v in arriba.items())
            )
            c.pasa = (
                internos.status_code == 200 and remisiones.status_code == 200
                and alta.status_code == 201
                and arriba == {"ms-pacientes": True, "ms-solicitudes": True, "ms-cobros": False}
            )
    finally:
        docker.iniciar(COBROS)
        listo = esperar_cobros()
        rep.nota(
            f"Se volvió a encender {COBROS} (estado: {docker.estado(COBROS)}; "
            f"{'responde' if listo else 'NO responde tras 90 s'})."
        )

    with rep.caso(
        "Recuperación al volver a encender cobros",
        "RNF-11 y RNF-14",
        "Cobros vuelve a responder por el gateway y una visita nueva sí genera su cargo",
    ) as c:
        consulta = gw.get("CAJA", "/api/cargos", params={"paciente_id": paciente["codigo"]})
        nueva = ctx.remision(paciente, "Cardiologia", etiqueta="I recuperacion")
        r = ctx.convertir(nueva["id"], "Cardiologia")
        generado = r.json()["visita"]["cargo_generado"] if r.status_code == 201 else None
        c.obtenido = (
            f"consulta de cargos: {consulta.status_code} · visita nueva: {r.status_code}, "
            f"cargo_generado={generado}"
        )
        c.pasa = consulta.status_code == 200 and r.status_code == 201 and generado is True

    with rep.caso(
        "El cargo pendiente se genera solo cuando cobros vuelve",
        "RNF-13",
        "La visita programada durante la caída recibe su cargo automáticamente",
    ) as c:
        c.pendiente = True
        c.motivo_pendiente = (
            "el ERS declara que la regeneración automática del cargo aún no está "
            "implementada (CU-08, flujo alterno); mientras tanto el cargo se genera "
            "desde la pantalla de cuentas."
        )
        if visita_sin_cargo is None:
            raise RuntimeError("no se llegó a crear la visita durante la caída")
        time.sleep(5)  # margen razonable para un reintento automático
        v = gw.get("FUNDACION", f"/api/visitas/{visita_sin_cargo['id']}").json()
        c.obtenido = (
            f"visita {v['id']} tras la recuperación: cargo_generado={v['cargo_generado']}, "
            f"cargo_id={v['cargo_id']}"
        )
        c.pasa = v["cargo_generado"] is True
