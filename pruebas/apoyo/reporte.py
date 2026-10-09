"""
El reporte de pruebas.

Cada caso se imprime en la consola en cuanto termina, para ver avanzar la
corrida, y al final todo se guarda tal cual en pruebas/resultado.txt. Ese
archivo es la evidencia del plan de pruebas: por eso el formato esta
fijado aqui y en ningun otro lado.

Hay tres veredictos, no dos:

  PASA                 el sistema hizo lo que pide el requisito
  FALLA                el sistema NO lo hizo; el reporte dice que obtuvo
  PENDIENTE CONOCIDO   el requisito no esta implementado y el propio ERS
                       lo declara asi. No cuenta como fallo, pero se
                       muestra para que no parezca que se olvido probarlo.
"""

import textwrap
from contextlib import contextmanager

ANCHO = 78
SANGRIA = " " * 7
# "Esperado: " y "Obtenido: " miden lo mismo; el texto que no cabe en
# una linea sigue alineado debajo del primer caracter del valor.
SANGRIA_VALOR = SANGRIA + " " * len("Obtenido: ")

PASA = "PASA"
FALLA = "FALLA"
PENDIENTE = "PENDIENTE"

ETIQUETA = {
    PASA: "[ PASA ]",
    FALLA: "[ FALLA ]",
    PENDIENTE: "[ PENDIENTE CONOCIDO ]",
}

LINEA_DOBLE = "=" * ANCHO
LINEA_SIMPLE = "-" * ANCHO


class Caso:
    """
    Un caso de prueba mientras se ejecuta.

    La prueba llena 'obtenido' y 'pasa'. Si el requisito es un pendiente
    que el ERS ya declara, se marca 'pendiente' con su motivo: cuando no
    pasa, el veredicto es PENDIENTE CONOCIDO en vez de FALLA.
    """

    def __init__(self, numero: int, grupo: str, nombre: str, verifica: str, esperado: str):
        self.numero = numero
        self.grupo = grupo
        self.nombre = nombre
        self.verifica = verifica
        self.esperado = esperado
        self.obtenido = ""
        self.pasa = False
        self.pendiente = False
        self.motivo_pendiente = ""

    @property
    def identificador(self) -> str:
        return f"CP-{self.numero:02d}"

    @property
    def veredicto(self) -> str:
        if self.pasa:
            return PASA
        return PENDIENTE if self.pendiente else FALLA


class Reporte:
    def __init__(self):
        self.lineas: list[str] = []
        self.casos: list[Caso] = []
        self.grupos: list[tuple[str, str]] = []
        self.grupo_actual = ""

    # ------------------------------------------------------------ salida

    def escribir(self, texto: str = "") -> None:
        print(texto, flush=True)
        self.lineas.append(texto)

    def parrafo(self, texto: str, sangria: str = " ") -> None:
        """Texto libre ajustado al ancho del reporte."""
        for bloque in texto.split("\n"):
            if not bloque.strip():
                self.escribir("")
                continue
            for linea in textwrap.wrap(bloque, ANCHO - len(sangria)) or [""]:
                self.escribir(sangria + linea)

    def titulo(self, texto: str) -> None:
        self.escribir("")
        self.escribir(LINEA_DOBLE)
        self.escribir(f" {texto}")
        self.escribir(LINEA_DOBLE)

    def guardar(self, ruta: str) -> None:
        # utf-8-sig agrega la marca BOM: el Bloc de notas y Word abren el
        # archivo con las tildes bien sin tener que elegir la codificacion.
        with open(ruta, "w", encoding="utf-8-sig", newline="\r\n") as archivo:
            archivo.write("\n".join(self.lineas) + "\n")

    # ------------------------------------------------------------ grupos

    def grupo(self, letra: str, titulo: str, descripcion: str = "") -> None:
        self.grupo_actual = letra
        self.grupos.append((letra, titulo))
        self.escribir("")
        self.escribir(LINEA_SIMPLE)
        self.escribir(f" {letra} · {titulo.upper()}")
        if descripcion:
            self.parrafo(descripcion, sangria=" ")
        self.escribir(LINEA_SIMPLE)
        self.escribir("")

    def nota(self, texto: str) -> None:
        """Aclaracion dentro de un grupo que no es un caso de prueba."""
        self.parrafo(f"Nota: {texto}", sangria=SANGRIA)
        self.escribir("")

    # ------------------------------------------------------------- casos

    @contextmanager
    def caso(self, nombre: str, verifica: str, esperado: str):
        """
        Envuelve un caso de prueba.

        Si la prueba lanza una excepcion, el caso no tumba la corrida: se
        registra como FALLA y el texto de la excepcion pasa a ser el
        resultado obtenido. Asi el reporte siempre dice QUE ocurrio, y los
        casos siguientes se ejecutan igual.

        Solo se atrapa Exception: Ctrl+C (KeyboardInterrupt) debe seguir
        de largo hasta el bloque que limpia los datos y restaura el sistema.
        """
        caso = Caso(len(self.casos) + 1, self.grupo_actual, nombre, verifica, esperado)
        try:
            yield caso
        except Exception as error:  # noqa: BLE001 - ver el docstring
            caso.pasa = False
            previo = f"{caso.obtenido}\n" if caso.obtenido else ""
            caso.obtenido = (
                f"{previo}La prueba no pudo completarse: {type(error).__name__}: {error}"
            )
        self.casos.append(caso)
        self._imprimir(caso)

    def _imprimir(self, caso: Caso) -> None:
        etiqueta = ETIQUETA[caso.veredicto]
        cabeza = f"{caso.identificador}  "
        espacio_nombre = ANCHO - len(cabeza) - len(etiqueta) - 2
        nombre = textwrap.wrap(caso.nombre, espacio_nombre) or [""]

        self.escribir((cabeza + nombre[0]).ljust(ANCHO - len(etiqueta)) + etiqueta)
        for resto in nombre[1:]:
            self.escribir(SANGRIA + resto)

        self._campo("Verifica", caso.verifica)
        self._campo("Esperado", caso.esperado)
        self._campo("Obtenido", caso.obtenido or "(la prueba no registró ningún resultado)")
        if caso.veredicto == PENDIENTE and caso.motivo_pendiente:
            self._campo("Pendiente", caso.motivo_pendiente)
        self.escribir("")

    def _campo(self, etiqueta: str, valor: str) -> None:
        prefijo = f"{SANGRIA}{etiqueta}: "
        sangria = " " * len(prefijo)
        primera = True
        for bloque in str(valor).split("\n"):
            lineas = textwrap.wrap(
                bloque,
                width=ANCHO,
                initial_indent=prefijo if primera else sangria,
                subsequent_indent=sangria,
                break_long_words=True,
            )
            for linea in lineas:
                self.escribir(linea)
            primera = False

    # ----------------------------------------------------------- resumen

    def contar(self, letra: str | None = None) -> dict[str, int]:
        casos = [c for c in self.casos if letra is None or c.grupo == letra]
        return {
            "total": len(casos),
            PASA: sum(c.veredicto == PASA for c in casos),
            FALLA: sum(c.veredicto == FALLA for c in casos),
            PENDIENTE: sum(c.veredicto == PENDIENTE for c in casos),
        }

    def fallidos(self) -> list[Caso]:
        return [c for c in self.casos if c.veredicto == FALLA]

    def pendientes(self) -> list[Caso]:
        return [c for c in self.casos if c.veredicto == PENDIENTE]

    def resumen(self) -> None:
        self.titulo("RESUMEN DE LA CORRIDA")
        self.escribir("")
        self.escribir(f" {'Grupo':<40}{'Casos':>7}{'Pasan':>8}{'Fallan':>8}{'Pend.':>8}")
        self.escribir(" " + "-" * (ANCHO - 2))
        for letra, titulo in self.grupos:
            n = self.contar(letra)
            nombre = f"{letra} · {titulo}"[:39]
            self.escribir(
                f" {nombre:<40}{n['total']:>7}{n[PASA]:>8}{n[FALLA]:>8}{n[PENDIENTE]:>8}"
            )
        self.escribir(" " + "-" * (ANCHO - 2))
        t = self.contar()
        self.escribir(
            f" {'TOTAL':<40}{t['total']:>7}{t[PASA]:>8}{t[FALLA]:>8}{t[PENDIENTE]:>8}"
        )
        self.escribir("")

        fallidos = self.fallidos()
        if fallidos:
            self.escribir(f" Casos que fallaron ({len(fallidos)}):")
            self.escribir("")
            for caso in fallidos:
                self._linea_de_lista(caso)
        else:
            self.escribir(" Ningún caso falló.")
            self.escribir("")

        pendientes = self.pendientes()
        if pendientes:
            self.escribir(
                f" Pendientes conocidos ({len(pendientes)}). No son fallos: el ERS los "
                "declara como no implementados."
            )
            self.escribir("")
            for caso in pendientes:
                self._linea_de_lista(caso)

    def _linea_de_lista(self, caso: Caso) -> None:
        self.parrafo(f"{caso.identificador}  {caso.nombre}  ({caso.verifica})", sangria="   ")
        primera = caso.obtenido.split("\n")[0]
        for linea in textwrap.wrap(
            f"Obtenido: {primera}", ANCHO - 10, subsequent_indent=" " * 10
        ):
            self.escribir("         " + linea)
        self.escribir("")
