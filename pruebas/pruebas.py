"""
Pruebas automatizadas del Sistema del Asilo "Cabeza de Algodon".

No se corre directamente: lo lanza ejecutar.ps1 dentro de un contenedor
de un solo uso, conectado a la red del docker-compose.

Recorre los grupos A a M en orden, numerando los casos CP-01 en adelante
sin reiniciar entre grupos, y al final SIEMPRE limpia los datos de prueba
y deja el sistema como estaba, aunque un caso haya fallado o la corrida
se haya cortado con Ctrl+C.

Codigo de salida: 0 si ningun caso fallo, 1 si alguno fallo. Un
"pendiente conocido" (requisito que el ERS declara no implementado) no
cuenta como fallo.
"""

import os
import signal
import sys

from apoyo.contexto import Contexto, fecha_en_palabras
from apoyo.docker import CONTENEDORES
from apoyo.limpieza import datos_de_prueba, limpiar
from apoyo.reporte import LINEA_DOBLE
from grupos import (
    a_infraestructura,
    b_autenticacion,
    c_bloqueo,
    d_permisos,
    e_defensa,
    f_internos,
    g_circuito_clinico,
    h_cobros,
    i_tolerancia,
    j_aislamiento,
    k_inyeccion,
    l_correo,
    m_bitacora,
)

GRUPOS = (
    a_infraestructura,
    b_autenticacion,
    c_bloqueo,
    d_permisos,
    e_defensa,
    f_internos,
    g_circuito_clinico,
    h_cobros,
    i_tolerancia,
    j_aislamiento,
    k_inyeccion,
    l_correo,
    m_bitacora,
)

RESULTADO = "/pruebas/resultado.txt"


def detener_con_limpieza(*_):
    """
    'docker stop' o cerrar la ventana mandan SIGTERM. Se convierte en el
    mismo corte que Ctrl+C para que el bloque finally limpie igual.
    """
    raise KeyboardInterrupt


def encabezado(ctx) -> None:
    rep, docker = ctx.rep, ctx.docker
    version = docker.version()
    plataforma = (version.get("Platform") or {}).get("Name", "Docker")
    imagenes = []
    for nombre in CONTENEDORES:
        datos = docker.inspeccionar(nombre)
        imagen = datos["Config"]["Image"] if datos else "no existe"
        imagenes.append(f"{nombre} ({imagen})")

    rep.escribir(LINEA_DOBLE)
    rep.escribir(" SISTEMA PARA ADMINISTRACIÓN DEL ASILO DE ANCIANOS «CABEZA DE ALGODÓN»")
    rep.escribir(" Reporte de pruebas automatizadas del sistema")
    rep.escribir(LINEA_DOBLE)
    rep.escribir(f" Fecha y hora de ejecución: {fecha_en_palabras(ctx.momento)}")
    rep.escribir(f" Marca de los datos:        {ctx.marca}")
    rep.escribir("")
    rep.escribir(" Entorno")
    rep.escribir(f"   Máquina:            {os.getenv('ENTORNO_WINDOWS') or 'no informado'}")
    rep.escribir(
        f"   Docker:             {plataforma} · motor {version.get('Version')} "
        f"({version.get('Os')}/{version.get('Arch')})"
    )
    rep.escribir(f"   Código probado:     {os.getenv('CODIGO_GIT') or 'no informado'}")
    rep.escribir(f"   Base de datos:      MySQL {ctx.root.uno('SELECT VERSION()')}")
    rep.escribir("   Punto de entrada:   gateway, http://localhost:8080 (desde la red interna, gateway:8080)")
    rep.parrafo("Contenedores:       " + ", ".join(imagenes), sangria="   ")
    rep.escribir("")
    rep.escribir(" Veredictos")
    rep.escribir("   PASA                el sistema cumple lo que pide el requisito")
    rep.escribir("   FALLA               el sistema no lo cumple; «Obtenido» dice qué hizo")
    rep.escribir("   PENDIENTE CONOCIDO  requisito que el ERS declara no implementado;")
    rep.escribir("                       se muestra, pero no cuenta como fallo")

    restos = {k: len(v) for k, v in datos_de_prueba(ctx).items() if v}
    if restos:
        rep.escribir("")
        rep.parrafo(
            "Aviso: había datos de pruebas anteriores que no se limpiaron ("
            + ", ".join(f"{k}: {v}" for k, v in restos.items())
            + "). Se borrarán junto con los de esta corrida.",
            sangria=" ",
        )


def main() -> int:
    signal.signal(signal.SIGTERM, detener_con_limpieza)
    ctx = Contexto()
    rep = ctx.rep
    encabezado(ctx)

    interrumpida = False
    quedo_igual = False
    try:
        for grupo in GRUPOS:
            rep.grupo(grupo.LETRA, grupo.TITULO, grupo.DESCRIPCION)
            grupo.ejecutar(ctx)

            # Si despues de la infraestructura no se puede ni entrar al
            # sistema, los otros 150 casos fallarian todos por lo mismo y
            # taparian la causa real. Se corta aqui y se dice por que.
            if grupo is a_infraestructura:
                try:
                    ctx.gw.como("ADMIN")
                except Exception as error:  # noqa: BLE001
                    rep.nota(
                        f"No se puede ingresar al sistema ({error}). Se omiten los grupos "
                        "B a M: fallarían todos por esta misma causa."
                    )
                    break
    except KeyboardInterrupt:
        interrumpida = True
        rep.escribir("")
        rep.parrafo("*** Corrida interrumpida. Se limpia y se restaura el sistema antes de salir. ***")
    finally:
        try:
            quedo_igual = limpiar(ctx)
        except Exception as error:  # noqa: BLE001
            rep.escribir("")
            rep.parrafo(
                f"LA LIMPIEZA NO TERMINÓ: {type(error).__name__}: {error}. Revise a mano los "
                f"datos con la marca «{ctx.marca}» y el estado de los contenedores."
            )
        rep.resumen()
        fallos = len(rep.fallidos())
        rep.escribir("")
        if interrumpida:
            veredicto = "CORRIDA INTERRUMPIDA: el reporte está incompleto."
        elif fallos:
            veredicto = f"RESULTADO: {fallos} caso(s) fallaron."
        else:
            veredicto = "RESULTADO: todos los casos pasaron."
        rep.escribir(f" {veredicto}")
        if not quedo_igual:
            rep.escribir(" ATENCIÓN: la limpieza dejó diferencias; ver la sección de limpieza.")
        rep.escribir(LINEA_DOBLE)
        rep.guardar(RESULTADO)

    return 1 if (fallos or interrumpida) else 0


if __name__ == "__main__":
    sys.exit(main())
