"""
E · Defensa en profundidad

El grupo D usa las rutas como las usaria la interfaz. Este grupo arma
las peticiones a mano, como lo haria alguien que quiere saltarse el
control: rutas con "..", cookies inventadas, encabezados que dicen ser
el administrador.

Los casos de rutas apuntan a un riesgo concreto del gateway: el permiso
se decide por el PRIMER tramo de la ruta (/api/cargos/...), pero lo que
se reenvia es la ruta completa. Si algo en el camino resuelve el "..",
la peticion termina en otro recurso del mismo microservicio, con el
permiso del primero. Se prueban todas las formas conocidas de escribir
lo mismo: el ".." simple, codificado una y dos veces, la barra invertida
y las barras repetidas. Todas deben morir en el gateway con el mismo 404
que un recurso inexistente, y quedar anotadas en la bitacora.

El caso de control comprueba lo contrario: que una ruta legitima de
varios tramos (/api/cargos/N/pagar) siga funcionando.
"""

import time

from apoyo.gateway import detalle, resumen

LETRA = "E"
TITULO = "Defensa en profundidad"
DESCRIPCION = (
    "Peticiones construidas fuera de la interfaz: rutas con «..» en todas sus "
    "formas, sesiones falsificadas, encabezados de suplantación y recursos "
    "inexistentes."
)

NO_EXISTE_RECURSO = "Ese recurso no existe en el sistema."

ESPERADO_RUTA = f"404 «{NO_EXISTE_RECURSO}» en cada forma, igual que un recurso inexistente"


def tarifas_con(ctx, texto: str) -> list[dict]:
    return ctx.root.consulta(
        "SELECT id, concepto FROM asilo_cobros.tarifas WHERE concepto LIKE %s", (f"%{texto}%",)
    )


def intento_por_ruta(ctx, nombre: str, verifica: str, rol: str, metodo: str,
                     rutas: list[str], intentos: list) -> None:
    """
    Un intento de saltarse el permiso armando la ruta a mano.

    Con POST se intenta crear una tarifa (lo que el rol no puede hacer) y
    se revisa en la base si se creo; con GET se intenta leer los cargos y
    se revisa si la respuesta trajo datos. El 404 tiene que ser el del
    gateway, con su mensaje: un 404 del microservicio querria decir que la
    peticion SI llego hasta el.

    Cada peticion que llega al gateway se anota en 'intentos', para que el
    caso de la bitacora sepa cuantas filas debe encontrar.
    """
    rep, gw = ctx.rep, ctx.gw
    esperado = ESPERADO_RUTA + ("; ninguna tarifa creada" if metodo == "POST" else "; sin datos")
    with rep.caso(nombre, verifica, esperado) as c:
        lineas, todo_bien = [], True
        for ruta in rutas:
            concepto = f"{ctx.marca} E ruta {ctx.sello}-{len(intentos) + 1}"
            cuerpo = None
            if metodo == "POST":
                cuerpo = {"concepto": concepto, "tipo": "CITA", "precio": 1.0,
                          "descuento_fundacion": 0, "activo": True}
            r = gw.crudo(metodo, ruta, gw.como(rol), json=cuerpo)
            intentos.append((rol, metodo, ruta, r.status_code))

            linea = f"{ruta} → {resumen(r)}"
            if metodo == "POST":
                creadas = tarifas_con(ctx, concepto)
                for fila in creadas:
                    ctx.creados["tarifas"].append(fila["id"])
                if creadas:
                    linea += f" · TARIFA CREADA (id {creadas[0]['id']}): ESCALADA DE PRIVILEGIOS"
                todo_bien &= not creadas
            elif r.status_code == 200:
                linea += " · LECTURA NO AUTORIZADA"
            lineas.append(linea)
            todo_bien &= r.status_code == 404 and detalle(r) == NO_EXISTE_RECURSO
        c.obtenido = "\n".join(lineas)
        c.pasa = todo_bien


def ejecutar(ctx) -> None:
    rep, gw, docker = ctx.rep, ctx.gw, ctx.docker

    bitacora_antes = ctx.root.uno("SELECT COALESCE(MAX(id), 0) FROM asilo_gateway.bitacora")
    intentos: list = []
    crear = "RNF-02 (Fundación no puede modificar el tarifario)"
    leer = "RNF-02 (el Médico general no consulta cargos)"

    intento_por_ruta(ctx, "Fundación crea una tarifa con «..» en la ruta", crear,
                     "FUNDACION", "POST", ["/api/cargos/../tarifas"], intentos)
    intento_por_ruta(ctx, "Fundación crea una tarifa con «..» codificado", crear,
                     "FUNDACION", "POST", ["/api/cargos/%2e%2e/tarifas"], intentos)
    intento_por_ruta(ctx, "Médico general lee los cargos con «..» en la ruta", leer,
                     "MEDICO_GENERAL", "GET", ["/api/tarifas/../cargos"], intentos)
    intento_por_ruta(ctx, "Fundación crea una tarifa con «..» codificado dos veces", crear,
                     "FUNDACION", "POST", ["/api/cargos/%252e%252e/tarifas"], intentos)
    intento_por_ruta(ctx, "Fundación crea una tarifa con barra invertida", crear,
                     "FUNDACION", "POST",
                     ["/api/cargos/..\\tarifas", "/api/cargos/..%5Ctarifas"], intentos)
    intento_por_ruta(ctx, "Médico general lee los cargos con barras repetidas", leer,
                     "MEDICO_GENERAL", "GET",
                     ["/api/tarifas//cargos", "/api/tarifas/%2F%2Fcargos"], intentos)

    with rep.caso(
        "Los intentos por ruta quedan anotados en la bitácora",
        "RNF-02 · bitácora de auditoría",
        "Una fila por intento, con el usuario, el método, la ruta y el código 404, "
        "también para las lecturas",
    ) as c:
        filas = ctx.root.consulta(
            """SELECT usuario, metodo, recurso, codigo FROM asilo_gateway.bitacora
               WHERE id > %s AND codigo = 404 AND usuario IN ('fundacion', 'medico')
               ORDER BY id""",
            (bitacora_antes,),
        )
        lecturas = sum(1 for f in filas if f["metodo"] == "GET")
        c.obtenido = (
            f"intentos hechos: {len(intentos)} · filas 404 en la bitácora: {len(filas)} "
            f"({lecturas} de lectura)"
        )
        if filas:
            f = filas[0]
            c.obtenido += f" · ejemplo: {f['usuario']} · {f['metodo']} {f['recurso']} · {f['codigo']}"
        c.pasa = len(filas) == len(intentos) and lecturas == sum(1 for i in intentos if i[1] == "GET")

    with rep.caso(
        "Control: una ruta legítima de varios tramos sigue funcionando",
        "RNF-02 (la corrección no bloquea lo permitido)",
        "Caja registra el pago con POST /api/cargos/N/pagar y recibe 200 con el "
        "cargo PAGADO",
    ) as c:
        tarifa = ctx.tarifa("E control pagar", "EXAMEN", 10.00, 0)
        cargo = ctx.crear_cargo(ctx.cuenta_de_prueba("E1"), tarifa)
        if cargo.status_code != 201:
            raise RuntimeError(f"no se pudo crear el cargo de control: {resumen(cargo)}")
        cargo_id = cargo.json()["id"]
        r = gw.post("CAJA", f"/api/cargos/{cargo_id}/pagar")
        estado = r.json().get("estado") if r.status_code == 200 else None
        c.obtenido = f"POST /api/cargos/{cargo_id}/pagar → {r.status_code}" + (f" · {estado}" if estado else f" · {resumen(r)}")
        c.pasa = r.status_code == 200 and estado == "PAGADO"

    with rep.caso(
        "Sesión falsificada y encabezados de suplantación",
        "RNF-02 (la identidad sale solo de la sesión)",
        "Cookie inventada → 401; Médico general con encabezados «X-Rol: ADMIN», "
        "«X-Usuario: admin», «X-HTTP-Method-Override: GET» o «?rol=ADMIN» → 403",
    ) as c:
        falsa = gw.crudo("GET", "/api/pacientes", "inventado-" + ctx.sello)
        medico = gw.como("MEDICO_GENERAL")
        suplantacion = gw.pedir(
            "DELETE", "/api/tarifas/999999999", medico,
            headers={"X-Rol": "ADMIN", "X-Usuario": "admin", "X-Forwarded-User": "admin",
                     "X-HTTP-Method-Override": "GET"},
        )
        por_parametro = gw.pedir("POST", "/api/tarifas", medico, params={"rol": "ADMIN"}, json={})
        c.obtenido = (
            f"cookie inventada: {resumen(falsa)}\n"
            f"encabezados de suplantación: {resumen(suplantacion)}\n"
            f"parámetro ?rol=ADMIN: {resumen(por_parametro)}"
        )
        c.pasa = (
            falsa.status_code == 401
            and suplantacion.status_code == 403
            and por_parametro.status_code == 403
        )

    with rep.caso(
        "Recurso inexistente",
        "Enrutamiento del gateway (negación por omisión)",
        "404 del gateway para un recurso que no está en su tabla de rutas, y 404 del "
        "servicio para un registro que no existe",
    ) as c:
        recurso = gw.get("ADMIN", "/api/usuarios")
        registro = gw.get("ADMIN", "/api/pacientes/PAC-NOEXISTE")
        c.obtenido = f"/api/usuarios: {resumen(recurso)}\n/api/pacientes/PAC-NOEXISTE: {resumen(registro)}"
        c.pasa = (
            recurso.status_code == 404 and detalle(recurso) == NO_EXISTE_RECURSO
            and registro.status_code == 404 and detalle(registro) != NO_EXISTE_RECURSO
        )

    with rep.caso(
        "El microservicio nunca recibe una petición no autorizada",
        "RNF-02 · el 403 ocurre antes del reenvío",
        "Las peticiones negadas no aparecen en el registro de acceso del microservicio; "
        "una petición permitida de control sí aparece",
    ) as c:
        # Cada peticion lleva un identificador que no se repite en ninguna
        # otra parte de la corrida. Buscar algo generico como "POST /tarifas"
        # encontraria las peticiones de los casos anteriores, que caen dentro
        # del mismo segundo del registro.
        desde = int(time.time()) - 1
        negado_pacientes = f"PACX{ctx.sello}"
        negado_tarifas = f"9{ctx.sello[-8:]}"
        control = f"PACCTRL{ctx.sello}"

        r1 = gw.delete("CAJA", f"/api/pacientes/{negado_pacientes}")
        r2 = gw.delete("MEDICO_GENERAL", f"/api/tarifas/{negado_tarifas}")
        r3 = gw.get("ADMIN", f"/api/pacientes/{control}")
        time.sleep(1.5)  # el registro del contenedor se escribe con un leve retraso

        log_pacientes = docker.registros("asilo-ms-pacientes", desde)
        log_cobros = docker.registros("asilo-ms-cobros", desde)
        llego_pacientes = negado_pacientes in log_pacientes
        llego_tarifas = f"/tarifas/{negado_tarifas}" in log_cobros
        llego_control = control in log_pacientes

        c.obtenido = (
            f"Caja DELETE /api/pacientes/{negado_pacientes}: {r1.status_code} · en el "
            f"registro de ms-pacientes: {'SÍ' if llego_pacientes else 'no'}\n"
            f"Médico general DELETE /api/tarifas/{negado_tarifas}: {r2.status_code} · en el "
            f"registro de ms-cobros: {'SÍ' if llego_tarifas else 'no'}\n"
            f"Control, Administrador GET /api/pacientes/{control}: {r3.status_code} · en el "
            f"registro: {'sí' if llego_control else 'NO (el método de verificación no sirve)'}"
        )
        c.pasa = (
            r1.status_code == 403 and r2.status_code == 403
            and not llego_pacientes and not llego_tarifas and llego_control
        )
