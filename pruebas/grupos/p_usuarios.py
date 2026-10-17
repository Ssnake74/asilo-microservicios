"""
P · Administracion de usuarios

RF-06 y lo que pidio el ingeniero al revisarlo: el administrador crea
cuentas con contrasena temporal, la restablece a quien la olvida, cambia
el puesto y desactiva a quien deja el asilo. Quien entra con contrasena
temporal no puede hacer nada hasta elegir la suya.

Los usuarios de prueba llevan la marca en el nombre completo: no hay
operacion de borrado y la limpieza los encuentra por ella.
"""

from apoyo.gateway import NOMBRE_ROL, ROLES, resumen

LETRA = "P"
TITULO = "Administración de usuarios"
DESCRIPCION = (
    "Altas con contraseña temporal, cambio obligatorio de contraseña, desactivación, "
    "restablecimiento, cambio de puesto y quién puede hacerlo."
)

NUEVA = "Prueba2026x"


def ejecutar(ctx) -> None:
    rep, gw, root = ctx.rep, ctx.gw, ctx.root
    A = "ADMIN"

    def nombre_usuario(sufijo: str) -> str:
        return f"prueba.{ctx.sello}.{sufijo}"

    def crear(sufijo: str, rol: str = "SECRETARIA", **cambios):
        cuerpo = {"usuario": nombre_usuario(sufijo), "nombre": f"{ctx.marca} {sufijo}", "rol": rol}
        cuerpo.update(cambios)
        return gw.post(A, "/api/usuarios", json=cuerpo)

    def apoyo(sufijo: str, rol: str = "SECRETARIA") -> dict:
        r = crear(sufijo, rol)
        if r.status_code != 201:
            raise RuntimeError(f"no se pudo crear el usuario de apoyo: {resumen(r)}")
        return r.json()

    def entrar(usuario: str, contrasena: str):
        r = gw.ingresar(usuario, contrasena)
        return r, gw.testigo_de(r)

    def poner_propia(usuario: dict) -> str:
        """Entra con la temporal y elige NUEVA; devuelve la sesion abierta."""
        _, testigo = entrar(usuario["usuario"], usuario["contrasena_temporal"])
        r = gw.pedir("POST", "/api/mi-contrasena", testigo,
                     json={"actual": usuario["contrasena_temporal"], "nueva": NUEVA})
        if r.status_code != 200:
            raise RuntimeError(f"no se pudo poner la contraseña propia: {resumen(r)}")
        return testigo

    with rep.caso(
        "El administrador crea un usuario con contraseña temporal",
        "RF-06",
        "201 con el usuario en minúsculas, el nombre sin espacios de más, una contraseña "
        "temporal y la marca de que debe cambiarla; en la base no queda la temporal legible",
    ) as c:
        r = crear("p1", nombre=f"  {ctx.marca}    p1  ", usuario=f"  PRUEBA.{ctx.sello}.P1 ")
        u = r.json() if r.status_code == 201 else {}
        guardada = root.uno(
            "SELECT contrasena FROM asilo_gateway.usuarios WHERE usuario = %s", (u.get("usuario"),)
        ) or ""
        temporal = u.get("contrasena_temporal", "")
        c.obtenido = (
            f"{r.status_code} · usuario «{u.get('usuario')}» · nombre «{u.get('nombre')}» · "
            f"temporal de {len(temporal)} caracteres · debe_cambiar={u.get('debe_cambiar')} · "
            f"en la base: {'la temporal en claro' if temporal and temporal in guardada else 'sal$resumen'}"
        )
        c.pasa = (
            r.status_code == 201
            and u["usuario"] == nombre_usuario("p1")
            and u["nombre"] == f"{ctx.marca} p1"
            and len(temporal) >= 12 and u["debe_cambiar"] is True
            and temporal not in guardada and "$" in guardada
        )
    p1 = u

    with rep.caso(
        "Datos rechazados al crear un usuario",
        "RF-06 (validación)",
        "409 para un usuario que ya existe; 422 para un usuario con espacios, para un "
        "rol que no existe y para un nombre en blanco",
    ) as c:
        repetido = crear("p1")
        con_espacio = gw.post(A, "/api/usuarios", json={
            "usuario": "ana lopez", "nombre": f"{ctx.marca} x", "rol": "CAJA"})
        rol_inventado = crear("p2x", rol="JEFE")
        en_blanco = crear("p2y", nombre="      ")
        c.obtenido = (
            f"repetido: {resumen(repetido)}\ncon espacio: {resumen(con_espacio)}\n"
            f"rol inventado: {resumen(rol_inventado)}\nnombre en blanco: {resumen(en_blanco)}"
        )
        c.pasa = (
            repetido.status_code == 409 and con_espacio.status_code == 422
            and rol_inventado.status_code == 422 and en_blanco.status_code == 422
        )

    with rep.caso(
        "Con la contraseña temporal solo se puede cambiarla",
        "RF-06 · cambio obligatorio",
        "El ingreso responde 200 con debe_cambiar; /api/yo responde 200; cualquier otro "
        "recurso responde 403 «Debe cambiar su contraseña antes de continuar.»",
    ) as c:
        r, testigo = entrar(p1["usuario"], p1["contrasena_temporal"])
        yo = gw.pedir("GET", "/api/yo", testigo)
        internos = gw.pedir("GET", "/api/pacientes", testigo)
        c.obtenido = (
            f"ingreso: {r.status_code} · debe_cambiar={r.json().get('debe_cambiar')} · "
            f"/api/yo: {yo.status_code} · /api/pacientes: {resumen(internos)}"
        )
        c.pasa = (
            r.status_code == 200 and r.json().get("debe_cambiar") is True
            and yo.status_code == 200
            and internos.status_code == 403
            and internos.json().get("detail") == "Debe cambiar su contraseña antes de continuar."
        )

    with rep.caso(
        "Reglas de la contraseña nueva",
        "RF-06 · cambio de contraseña",
        "422 con la actual equivocada, con menos de 8 caracteres, sin números y si repite "
        "la actual; 200 con una válida, y después la temporal ya no entra y la nueva sí",
    ) as c:
        _, testigo = entrar(p1["usuario"], p1["contrasena_temporal"])
        temporal = p1["contrasena_temporal"]

        def cambio(actual, nueva):
            return gw.pedir("POST", "/api/mi-contrasena", testigo, json={"actual": actual, "nueva": nueva})

        mala = cambio("noesesta1", NUEVA)
        corta = cambio(temporal, "abc12")
        sin_numeros = cambio(temporal, "solamenteletras")
        repetida = cambio(temporal, temporal)
        valida = cambio(temporal, NUEVA)
        internos = gw.pedir("GET", "/api/pacientes", testigo)
        vieja, _ = entrar(p1["usuario"], temporal)
        nueva, _ = entrar(p1["usuario"], NUEVA)
        c.obtenido = (
            f"actual equivocada: {resumen(mala)}\nmenos de 8: {resumen(corta)}\n"
            f"sin números: {resumen(sin_numeros)}\nrepite la actual: {resumen(repetida)}\n"
            f"válida: {valida.status_code} · luego /api/pacientes: {internos.status_code}\n"
            f"ingreso con la temporal: {vieja.status_code} · con la nueva: {nueva.status_code}, "
            f"debe_cambiar={nueva.json().get('debe_cambiar')}"
        )
        c.pasa = (
            mala.status_code == 422 and corta.status_code == 422
            and sin_numeros.status_code == 422 and repetida.status_code == 422
            and valida.status_code == 200 and internos.status_code == 200
            and vieja.status_code == 401
            and nueva.status_code == 200 and nueva.json().get("debe_cambiar") is False
        )

    with rep.caso(
        "Un usuario desactivado sale y ya no entra",
        "RF-06",
        "La desactivación responde 200; la sesión que tenía abierta da 401 en su "
        "siguiente petición; el ingreso da 401 con el mismo mensaje que una contraseña mala",
    ) as c:
        _, testigo = entrar(p1["usuario"], NUEVA)
        antes = gw.pedir("GET", "/api/pacientes", testigo)
        r = gw.put(A, f"/api/usuarios/{p1['id']}", json={"activo": False})
        despues = gw.pedir("GET", "/api/pacientes", testigo)
        ingreso, _ = entrar(p1["usuario"], NUEVA)
        c.obtenido = (
            f"antes: {antes.status_code} · desactivar: {r.status_code} · su sesión después: "
            f"{despues.status_code} · ingreso: {resumen(ingreso)}"
        )
        c.pasa = (
            antes.status_code == 200 and r.status_code == 200 and r.json()["activo"] is False
            and despues.status_code == 401
            and ingreso.status_code == 401
            and ingreso.json().get("detail") == "Usuario o contraseña incorrectos."
        )

    with rep.caso(
        "Reactivar y restablecer la contraseña olvidada",
        "RF-06 · restablecimiento",
        "Reactivar responde 200; restablecer da otra temporal, cierra sus sesiones y le "
        "quita el bloqueo; la contraseña anterior deja de entrar y la temporal entra con "
        "debe_cambiar",
    ) as c:
        reactivar = gw.put(A, f"/api/usuarios/{p1['id']}", json={"activo": True})
        _, testigo = entrar(p1["usuario"], NUEVA)
        for _ in range(5):
            entrar(p1["usuario"], "equivocada1")
        bloqueado, _ = entrar(p1["usuario"], NUEVA)
        r = gw.post(A, f"/api/usuarios/{p1['id']}/restablecer")
        temporal = r.json().get("contrasena_temporal", "") if r.status_code == 200 else ""
        sesion_vieja = gw.pedir("GET", "/api/yo", testigo)
        anterior, _ = entrar(p1["usuario"], NUEVA)
        con_temporal, _ = entrar(p1["usuario"], temporal)
        c.obtenido = (
            f"reactivar: {reactivar.status_code} · bloqueado antes de restablecer: "
            f"{bloqueado.status_code} · restablecer: {r.status_code} · su sesión anterior: "
            f"{sesion_vieja.status_code}\ncontraseña anterior: {anterior.status_code} · temporal: "
            f"{con_temporal.status_code}, debe_cambiar={con_temporal.json().get('debe_cambiar')}"
        )
        c.pasa = (
            reactivar.status_code == 200 and bloqueado.status_code == 429
            and r.status_code == 200 and temporal and temporal != p1["contrasena_temporal"]
            and sesion_vieja.status_code == 401
            and anterior.status_code == 401
            and con_temporal.status_code == 200 and con_temporal.json().get("debe_cambiar") is True
        )

    with rep.caso(
        "El cambio de puesto surte efecto en la siguiente petición",
        "RF-06 · RF-03",
        "Una secretaria con sesión abierta recibe 403 al registrar un cargo; el "
        "administrador la pasa a Caja y, con la misma sesión, la petición ya llega al "
        "servicio (422 por el cuerpo vacío)",
    ) as c:
        p3 = apoyo("p3", "SECRETARIA")
        testigo = poner_propia(p3)
        antes = gw.pedir("POST", "/api/cargos", testigo, json={})
        r = gw.put(A, f"/api/usuarios/{p3['id']}", json={"rol": "CAJA"})
        despues = gw.pedir("POST", "/api/cargos", testigo, json={})
        c.obtenido = (
            f"como Secretaria: {antes.status_code} · cambio a Caja: {r.status_code} · "
            f"misma sesión: {despues.status_code} (422: llegó al servicio con el cuerpo vacío)"
        )
        c.pasa = antes.status_code == 403 and r.status_code == 200 and despues.status_code == 422

    with rep.caso(
        "El administrador no puede dejarse fuera a sí mismo",
        "RF-06 (el sistema no se queda sin administrador)",
        "409 al desactivarse, al quitarse el rol y al restablecer su propia contraseña; "
        "cambiar su propio nombre sí se permite",
    ) as c:
        mio = next(u for u in gw.get(A, "/api/usuarios").json() if u["usuario"] == "admin")
        desactivar = gw.put(A, f"/api/usuarios/{mio['id']}", json={"activo": False})
        quitar_rol = gw.put(A, f"/api/usuarios/{mio['id']}", json={"rol": "CAJA"})
        restablecer = gw.post(A, f"/api/usuarios/{mio['id']}/restablecer")
        nombre = gw.put(A, f"/api/usuarios/{mio['id']}", json={"nombre": mio["nombre"]})
        c.obtenido = (
            f"desactivarse: {resumen(desactivar)}\nquitarse el rol: {resumen(quitar_rol)}\n"
            f"restablecerse: {resumen(restablecer)}\nsu nombre: {nombre.status_code}"
        )
        c.pasa = (
            desactivar.status_code == 409 and quitar_rol.status_code == 409
            and restablecer.status_code == 409 and nombre.status_code == 200
        )

    with rep.caso(
        "Solo el administrador maneja usuarios",
        "RF-06 · RNF-02",
        "403 para los otros roles al consultar, crear, modificar y restablecer; 401 sin "
        "sesión; ningún usuario creado por ellos",
    ) as c:
        lineas, todo_bien = [], True
        for rol in ROLES:
            if rol == A:
                continue
            codigos = (
                gw.get(rol, "/api/usuarios").status_code,
                gw.post(rol, "/api/usuarios", json={
                    "usuario": nombre_usuario(f"no{rol[:3].lower()}"),
                    "nombre": f"{ctx.marca} no", "rol": "ADMIN"}).status_code,
                gw.put(rol, f"/api/usuarios/{p1['id']}", json={"rol": "ADMIN"}).status_code,
                gw.post(rol, f"/api/usuarios/{p1['id']}/restablecer").status_code,
            )
            todo_bien &= all(cod == 403 for cod in codigos)
            lineas.append(f"{NOMBRE_ROL[rol]}: {', '.join(map(str, codigos))}")
        sin_sesion = gw.get(None, "/api/usuarios").status_code
        intrusos = root.uno(
            "SELECT COUNT(*) FROM asilo_gateway.usuarios WHERE usuario LIKE %s",
            (nombre_usuario("no") + "%",),
        )
        c.obtenido = " · ".join(lineas) + f"\nsin sesión: {sin_sesion} · creados por ellos: {intrusos}"
        c.pasa = todo_bien and sin_sesion == 401 and intrusos == 0

    with rep.caso(
        "La bitácora anota quién manejó qué cuenta, sin la contraseña",
        "RF-06 · bitácora de auditoría",
        "Filas del administrador para POST /api/usuarios (201), PUT /api/usuarios/N y "
        "POST /api/usuarios/N/restablecer; ninguna fila contiene una contraseña temporal",
    ) as c:
        filas = gw.get(A, "/api/bitacora", params={"usuario": "admin", "desde": ctx.inicio_sql,
                                                   "limite": 500}).json()
        def hay(metodo, recurso, codigo):
            return any(f["metodo"] == metodo and f["recurso"] == recurso and f["codigo"] == codigo
                       for f in filas)
        alta = hay("POST", "/api/usuarios", 201)
        cambio = hay("PUT", f"/api/usuarios/{p1['id']}", 200)
        restablecida = hay("POST", f"/api/usuarios/{p1['id']}/restablecer", 200)
        con_clave = root.uno(
            """SELECT COUNT(*) FROM asilo_gateway.bitacora
               WHERE id > %s AND (recurso LIKE %s OR recurso LIKE %s OR usuario LIKE %s)""",
            (ctx.inicial["max_bitacora"], f"%{p1['contrasena_temporal']}%", f"%{NUEVA}%", f"%{NUEVA}%"),
        )
        c.obtenido = (
            f"alta: {'sí' if alta else 'no'} · cambio: {'sí' if cambio else 'no'} · "
            f"restablecimiento: {'sí' if restablecida else 'no'} · filas con una contraseña: {con_clave}"
        )
        c.pasa = alta and cambio and restablecida and con_clave == 0
