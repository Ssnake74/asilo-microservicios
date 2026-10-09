"""
Restauracion del sistema y limpieza de los datos de prueba.

Corre SIEMPRE al final, haya pasado lo que haya pasado: desde el bloque
finally de pruebas.py. El orden importa:

  1. Contenedores: encender cobros, reanudar y reconectar Mailpit. Sin
     esto los borrados por la API fallarian.
  2. Intentos fallidos de la corrida, para que el Administrador pueda
     entrar a borrar.
  3. Borrado POR LA APLICACION de todo lo que la aplicacion permite borrar:
     cargos pendientes, tarifas sin cargos, internos.
  4. Borrado DIRECTO EN MYSQL, como root y filtrando por la marca, de lo
     que el sistema no deja borrar: remisiones y visitas (no existe esa
     operacion) y cargos pagados (RN-12), y lo que dependa de ellos.
  5. Correos de prueba en Mailpit.
  6. Cierre de las sesiones abiertas por la corrida.
  7. Filas de bitacora e intentos fallidos de la corrida. Va al final
     porque los pasos anteriores tambien dejan filas en la bitacora.
  8. Contadores AUTO_INCREMENT devueltos a su valor inicial.
  9. Verificacion: se vuelve a buscar la marca en todas partes.

Todo lo que se hace queda escrito en el reporte, con cantidades. Borrar
filas de una tabla de auditoria sin dejar constancia seria peor que no
limpiarla.
"""

import time

import httpx

from . import correo
from .contexto import PREFIJO_MARCA

MARCA_LIKE = f"%{PREFIJO_MARCA}%"


def _ids(filas: list[dict], campo: str = "id") -> list:
    return [f[campo] for f in filas]


def _lista(valores: list) -> str:
    valores = [str(v) for v in valores]
    if len(valores) <= 12:
        return ", ".join(valores)
    return ", ".join(valores[:12]) + f" y {len(valores) - 12} más"


# ---------------------------------------------------------------------
# Que datos de prueba hay en la base. Se busca por la marca Y por lo que
# la corrida anoto, por si algo se creo sin que el texto llevara la marca.
# ---------------------------------------------------------------------

def _en_lista(ids: list) -> tuple[str, tuple]:
    """Fragmento 'id IN (...)' seguro aun con la lista vacia."""
    if not ids:
        return "FALSE", ()
    return f"id IN ({', '.join(['%s'] * len(ids))})", tuple(ids)


def datos_de_prueba(ctx) -> dict[str, list[dict]]:
    root, creados = ctx.root, ctx.creados

    sql_ids, p_ids = _en_lista(creados["solicitudes"])
    solicitudes = root.consulta(
        f"""SELECT id, estado FROM asilo_solicitudes.solicitudes
            WHERE paciente_nombre LIKE %s OR motivo LIKE %s OR {sql_ids}""",
        (MARCA_LIKE, MARCA_LIKE, *p_ids),
    )
    sql_sol, p_sol = _en_lista(_ids(solicitudes))
    visitas = root.consulta(
        f"""SELECT id FROM asilo_solicitudes.visitas
            WHERE paciente_nombre LIKE %s OR {sql_sol.replace('id IN', 'solicitud_id IN')}""",
        (MARCA_LIKE, *p_sol),
    )

    sql_tar, p_tar = _en_lista(creados["tarifas"])
    tarifas = root.consulta(
        f"SELECT id FROM asilo_cobros.tarifas WHERE concepto LIKE %s OR {sql_tar}",
        (MARCA_LIKE, *p_tar),
    )
    sql_car, p_car = _en_lista(creados["cargos"])
    sql_ct, p_ct = _en_lista(_ids(tarifas))
    cargos = root.consulta(
        f"""SELECT id, estado FROM asilo_cobros.cargos
            WHERE paciente_nombre LIKE %s OR paciente_id LIKE %s OR {sql_car}
               OR {sql_ct.replace('id IN', 'tarifa_id IN')}""",
        (MARCA_LIKE, f"{PREFIJO_MARCA}%", *p_car, *p_ct),
    )

    codigos = creados["pacientes"]
    filtro_codigos = f"codigo IN ({', '.join(['%s'] * len(codigos))})" if codigos else "FALSE"
    pacientes = root.consulta(
        f"""SELECT id, codigo FROM asilo_pacientes.pacientes
            WHERE apellidos LIKE %s OR {filtro_codigos}""",
        (MARCA_LIKE, *codigos),
    )
    return {
        "solicitudes": solicitudes,
        "visitas": visitas,
        "cargos": cargos,
        "tarifas": tarifas,
        "pacientes": pacientes,
    }


def correos_de_prueba(ctx) -> list[str]:
    identificadores = set()
    consultas = [f'to:"{d}"' for d in set(ctx.creados["correos"])]
    consultas.append(f'subject:"{PREFIJO_MARCA}"')
    for consulta in consultas:
        try:
            identificadores.update(m["ID"] for m in correo.buscar(consulta))
        except httpx.HTTPError:
            pass
    return sorted(identificadores)


# ---------------------------------------------------------------------
# 1. Contenedores
# ---------------------------------------------------------------------

def restaurar_contenedores(ctx) -> list[str]:
    docker, inicial = ctx.docker, ctx.inicial
    acciones = []

    if docker.estado("asilo-mailpit") == "paused":
        docker.reanudar("asilo-mailpit")
        acciones.append("asilo-mailpit estaba en pausa: se reanudó.")
    if ctx.red and ctx.red not in docker.redes("asilo-mailpit"):
        docker.conectar(ctx.red, "asilo-mailpit", inicial["alias_correo"])
        acciones.append("asilo-mailpit estaba desconectado de la red: se reconectó.")

    for nombre, estado_inicial in inicial["contenedores"].items():
        actual = docker.estado(nombre)
        if estado_inicial == "running" and actual != "running":
            docker.iniciar(nombre)
            acciones.append(f"{nombre} estaba «{actual}»: se encendió.")

    if any("ms-cobros" in a for a in acciones):
        limite = time.time() + 90
        while time.time() < limite:
            try:
                if httpx.get("http://ms-cobros:8082/health", timeout=3).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(1)
    return acciones


# ---------------------------------------------------------------------
# Todo el proceso
# ---------------------------------------------------------------------

def limpiar(ctx) -> bool:
    """Devuelve True si el sistema quedo como estaba."""
    rep, root, gw, inicial = ctx.rep, ctx.root, ctx.gw, ctx.inicial
    rep.titulo("LIMPIEZA Y RESTAURACIÓN DEL SISTEMA")
    rep.escribir("")
    rep.parrafo(f"Marca de los datos de prueba: «{ctx.marca}».")
    rep.escribir("")

    # 1
    acciones = restaurar_contenedores(ctx)
    rep.parrafo("1. Contenedores: " + (" ".join(acciones) if acciones else
                "ninguno quedó detenido, pausado ni desconectado."))
    rep.escribir("")

    # 2
    root.ejecutar(
        "DELETE FROM asilo_gateway.intentos_fallidos WHERE id > %s", (inicial["max_intentos"],)
    )

    # 3. Por la aplicacion
    datos = datos_de_prueba(ctx)
    por_api = {"cargos": [], "tarifas": [], "pacientes": []}
    no_permitidos = []
    admin = gw.como("ADMIN")

    for fila in datos["cargos"]:
        r = gw.pedir("DELETE", f"/api/cargos/{fila['id']}", admin)
        if r.status_code == 204:
            por_api["cargos"].append(fila["id"])
        else:
            no_permitidos.append(f"cargo {fila['id']} ({fila['estado']}): la aplicación respondió {r.status_code}")
    for fila in datos["tarifas"]:
        r = gw.pedir("DELETE", f"/api/tarifas/{fila['id']}", admin)
        if r.status_code == 204:
            por_api["tarifas"].append(fila["id"])
        else:
            no_permitidos.append(f"tarifa {fila['id']}: la aplicación respondió {r.status_code}")
    for fila in datos["pacientes"]:
        r = gw.pedir("DELETE", f"/api/pacientes/{fila['codigo']}", admin)
        if r.status_code == 204:
            por_api["pacientes"].append(fila["codigo"])
        else:
            no_permitidos.append(f"interno {fila['codigo']}: la aplicación respondió {r.status_code}")

    rep.parrafo("2. Borrado por la aplicación (como Administrador, por el gateway):")
    rep.parrafo(f"Cargos pendientes: {len(por_api['cargos'])}"
                + (f" (id {_lista(por_api['cargos'])})" if por_api["cargos"] else ""), sangria="     ")
    rep.parrafo(f"Tarifas: {len(por_api['tarifas'])}"
                + (f" (id {_lista(por_api['tarifas'])})" if por_api["tarifas"] else ""), sangria="     ")
    rep.parrafo(f"Internos: {len(por_api['pacientes'])}"
                + (f" ({_lista(por_api['pacientes'])})" if por_api["pacientes"] else ""), sangria="     ")
    if no_permitidos:
        rep.parrafo("La aplicación no permitió borrar (se borran en el paso 3):", sangria="     ")
        for linea in no_permitidos:
            rep.parrafo(f"- {linea}", sangria="       ")
    rep.escribir("")

    # 4. Directo en MySQL, en orden de dependencia
    datos = datos_de_prueba(ctx)
    directo = {}
    pasos = [
        ("visitas", "asilo_solicitudes.visitas", "Visitas (el sistema no tiene operación de borrado)"),
        ("solicitudes", "asilo_solicitudes.solicitudes", "Remisiones (el sistema solo permite anularlas)"),
        ("cargos", "asilo_cobros.cargos", "Cargos que la aplicación no deja borrar (pagados, RN-12)"),
        ("tarifas", "asilo_cobros.tarifas", "Tarifas que tenían cargos pagados (RN-11)"),
        ("pacientes", "asilo_pacientes.pacientes", "Internos que la aplicación no dejó borrar"),
    ]
    for clave, tabla, _ in pasos:
        ids = _ids(datos[clave])
        if ids:
            sql, params = _en_lista(ids)
            root.ejecutar(f"DELETE FROM {tabla} WHERE {sql}", params)
        directo[clave] = ids

    rep.parrafo("3. Borrado directo en MySQL (como root, filtrando por la marca):")
    for clave, _, descripcion in pasos:
        ids = directo[clave]
        rep.parrafo(f"{descripcion}: {len(ids)}" + (f" (id {_lista(ids)})" if ids else ""), sangria="     ")
    rep.escribir("")

    # 5. Correos
    mensajes = correos_de_prueba(ctx)
    try:
        correo.borrar(mensajes)
        texto_correo = f"{len(mensajes)} mensaje(s) de prueba borrados de Mailpit; los demás no se tocaron."
    except httpx.HTTPError as error:
        texto_correo = f"no se pudieron borrar {len(mensajes)} mensaje(s) de prueba: {error}"
    rep.parrafo(f"4. Correo: {texto_correo}")
    rep.escribir("")

    # 6. Sesiones
    cerradas = 0
    for testigo in list(gw.testigos):
        try:
            if gw.pedir("POST", "/api/logout", testigo).status_code == 200:
                cerradas += 1
        except httpx.HTTPError:
            pass
    testigos = list(gw.testigos)
    restos_sesion = 0
    if testigos:
        marcadores = ", ".join(["%s"] * len(testigos))
        restos_sesion = root.ejecutar(
            f"DELETE FROM asilo_gateway.sesiones WHERE token IN ({marcadores})", tuple(testigos)
        )
    rep.parrafo(
        f"5. Sesiones: {len(testigos)} abiertas por la corrida, cerradas con «cerrar sesión»"
        + (f"; {restos_sesion} borradas directamente." if restos_sesion else ".")
    )
    rep.escribir("")

    # 7. Bitacora e intentos
    rango = root.consulta(
        "SELECT COUNT(*) AS n, MIN(id) AS desde, MAX(id) AS hasta FROM asilo_gateway.bitacora WHERE id > %s",
        (inicial["max_bitacora"],),
    )[0]
    borradas = root.ejecutar("DELETE FROM asilo_gateway.bitacora WHERE id > %s", (inicial["max_bitacora"],))
    intentos = root.ejecutar(
        "DELETE FROM asilo_gateway.intentos_fallidos WHERE id > %s", (inicial["max_intentos"],)
    )
    rep.parrafo(
        f"6. Bitácora: se BORRARON {borradas} filas generadas por esta corrida"
        + (f" (id {rango['desde']} a {rango['hasta']})" if borradas else "")
        + f". La tabla vuelve a sus {inicial['filas_bitacora']} filas anteriores a la corrida. "
        "Si alguien usó el sistema mientras corrían las pruebas, sus filas de ese "
        "intervalo también se borraron: no hay forma de distinguirlas."
    )
    rep.parrafo(f"Intentos fallidos de ingreso de la corrida borrados en este paso: {intentos}.",
                sangria="   ")
    rep.escribir("")

    # 8. Contadores
    actuales = root.contadores()
    lineas = []
    for tabla, valor in sorted(inicial["contadores"].items()):
        ahora = actuales.get(tabla)
        if ahora is not None and ahora != valor:
            root.ejecutar(f"ALTER TABLE {tabla} AUTO_INCREMENT = {int(valor)}")
            quedo = root.contadores().get(tabla)
            lineas.append(f"{tabla}: {ahora} → {quedo}" + ("" if quedo == valor else f" (se pidió {valor})"))
    rep.parrafo("7. Contadores AUTO_INCREMENT devueltos a su valor inicial: "
                + ("; ".join(lineas) if lineas else "ninguno había cambiado."))
    rep.escribir("")

    # 9. Verificacion
    rep.parrafo("8. Verificación final:")
    final = datos_de_prueba(ctx)
    quedan = {k: len(v) for k, v in final.items() if v}
    # Un aviso que estaba en camino puede llegar despues del paso 4: el
    # envio corre en segundo plano en ms-solicitudes. Si aparece, se borra
    # aqui y se deja dicho, en vez de darlo por un resto de la limpieza.
    correos_restantes = correos_de_prueba(ctx)
    if correos_restantes:
        try:
            correo.borrar(correos_restantes)
            rep.parrafo(
                f"   {len(correos_restantes)} aviso(s) de prueba llegaron a Mailpit después del "
                "paso 4 y se borraron en esta verificación."
            )
            correos_restantes = correos_de_prueba(ctx)
        except httpx.HTTPError:
            pass
    bitacora = root.uno("SELECT COUNT(*) FROM asilo_gateway.bitacora")
    intentos_final = root.uno("SELECT COUNT(*) FROM asilo_gateway.intentos_fallidos")
    contenedores = {n: ctx.docker.estado(n) for n in inicial["contenedores"]}
    distintos = {n: e for n, e in contenedores.items() if e != inicial["contenedores"][n]}
    contadores_final = root.contadores()
    contadores_distintos = [
        t for t, v in inicial["contadores"].items() if contadores_final.get(t) != v
    ]

    problemas = []
    if quedan:
        problemas.append("datos de prueba que quedaron: "
                         + ", ".join(f"{k} {v}" for k, v in quedan.items()))
    if correos_restantes:
        problemas.append(f"{len(correos_restantes)} correo(s) de prueba en Mailpit")
    if bitacora != inicial["filas_bitacora"]:
        problemas.append(f"bitácora con {bitacora} filas (había {inicial['filas_bitacora']})")
    if intentos_final != inicial["intentos"]:
        problemas.append(f"intentos fallidos: {intentos_final} (había {inicial['intentos']})")
    if distintos:
        problemas.append("contenedores en otro estado: "
                         + ", ".join(f"{n} {e}" for n, e in distintos.items()))
    if contadores_distintos:
        problemas.append("contadores distintos: " + ", ".join(contadores_distintos))

    if problemas:
        for p in problemas:
            rep.parrafo(f"- QUEDÓ: {p}", sangria="     ")
    else:
        rep.parrafo(
            "El sistema quedó como estaba: los 7 contenedores en su estado inicial "
            f"({', '.join(sorted(set(contenedores.values())))}), sin cuentas bloqueadas "
            f"({intentos_final} intentos fallidos guardados, igual que al empezar), sin "
            "internos, remisiones, visitas, tarifas, cargos ni correos de prueba, la "
            f"bitácora con sus {bitacora} filas originales y los contadores en su valor inicial.",
            sangria="     ",
        )
    return not problemas
