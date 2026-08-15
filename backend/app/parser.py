"""Parser de dominio: de texto hablado a items estructurados.

Deliberadamente **sin LLM**. Dos razones:

1. La invariante que Miguel dejó escrita en OdontoFlow (`AGENTS.md:19`):
   *"LLMs never set prices, durations, slots or bookings"*. Un modelo que
   alucina una cantidad de insumos produce un descuadre de inventario real.
2. Un catálogo cerrado con reglas es auditable: cuando falla, se sabe por qué
   y se arregla agregando un alias. Un LLM que falla solo se puede rezar.

El LLM, si algún día entra, va arriba de esto para redactar la nota clínica
libre — nunca para decidir cantidades ni productos.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field

# --------------------------------------------------------------- normalizar


def limpiar(texto: str) -> str:
    """minúsculas, sin tildes, sin puntuación. 'veintiséis' -> 'veintiseis'."""
    t = unicodedata.normalize("NFD", texto.lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    t = re.sub(r"[^\w\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


# ------------------------------------------------------- números en palabras

ATOMOS: dict[str, int] = {
    "cero": 0, "un": 1, "uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4,
    "cinco": 5, "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10,
    "once": 11, "doce": 12, "trece": 13, "catorce": 14, "quince": 15,
    "dieciseis": 16, "diecisiete": 17, "dieciocho": 18, "diecinueve": 19,
    "veinte": 20, "veintiuno": 21, "veintiun": 21, "veintiuna": 21,
    "veintidos": 22, "veintitres": 23, "veinticuatro": 24, "veinticinco": 25,
    "veintiseis": 26, "veintisiete": 27, "veintiocho": 28, "veintinueve": 29,
    "treinta": 30, "cuarenta": 40, "cincuenta": 50, "sesenta": 60,
    "setenta": 70, "ochenta": 80, "noventa": 90,
    "cien": 100, "ciento": 100, "doscientos": 200, "trescientos": 300,
    "cuatrocientos": 400, "quinientos": 500, "seiscientos": 600,
    "setecientos": 700, "ochocientos": 800, "novecientos": 900,
    "mil": 1000,
}
UNE = {"y"}

# Palabras que preceden a una cantidad y no deben romper la asociación:
# "me quedan como unas tres agujas".
RELLENO = {"como", "unas", "unos", "mas", "menos", "casi", "aprox", "aproximadamente",
           "creo", "que", "serian", "seran", "hay", "quedan", "tengo", "son", "de"}

# Marcas de autocorrección: "tres... no, cuatro". Lo que va DESPUÉS manda.
CORRECCION = {"no", "perdon", "perdona", "mejor", "digo", "osea", "o sea"}


@dataclass(frozen=True)
class NumeroHallado:
    valor: int
    inicio: int  # índice del token donde empieza
    fin: int     # índice del token siguiente al último


def numeros_con_posicion(tokens: list[str]) -> list[NumeroHallado]:
    """Números del texto (dígitos o palabras) con su posición en tokens.

    Una corrida de palabras-número puede contener VARIOS números: al dictar
    piezas dentales se dice "veintiséis y veintisiete", que son dos, no 53.
    """
    hallados: list[NumeroHallado] = []
    corrida: list[str] = []
    inicio = 0

    def cerrar(fin: int) -> None:
        nonlocal corrida
        if not corrida:
            return
        for valor, desp_ini, desp_fin in _valores(corrida):
            hallados.append(NumeroHallado(valor, inicio + desp_ini, inicio + desp_fin))
        corrida = []

    for i, tok in enumerate(tokens + ["\x00"]):
        if tok.isdigit():
            cerrar(i)
            hallados.append(NumeroHallado(int(tok), i, i + 1))
            continue
        if tok in ATOMOS or (tok in UNE and corrida):
            if not corrida:
                inicio = i
            corrida.append(tok)
            continue
        cerrar(i)
    return hallados


def _valores(corrida: list[str]) -> list[tuple[int, int, int]]:
    """Corta la corrida en números según cómo compone el español.

    Un número solo sigue creciendo si cada término es MENOR que el anterior
    ('ciento veinte' = 120, 'treinta y seis' = 36). Si aparece uno igual o
    mayor, empezó otro número ('veintiséis y veintisiete'). 'mil' multiplica.
    """
    out: list[tuple[int, int, int]] = []
    total = actual = 0
    ultimo: int | None = None
    ini = 0

    for idx, w in enumerate(corrida):
        if w in UNE:
            continue
        v = ATOMOS[w]
        if v == 1000:
            total += (actual or 1) * 1000
            actual = 0
            ultimo = 1000
            continue
        if ultimo is not None and v >= ultimo:
            out.append((total + actual, ini, idx))
            total = actual = 0
            ini = idx
        actual += v
        ultimo = v

    if total or actual or ultimo == 0:
        out.append((total + actual, ini, len(corrida)))
    return out


def numeros_en(texto: str) -> Counter:
    """Multiset de números del texto. Usado por los tests y el scorer."""
    return Counter(n.valor for n in numeros_con_posicion(limpiar(texto).split()))


# ----------------------------------------------------------------- catálogo


@dataclass(frozen=True)
class EntradaCatalogo:
    codigo: str
    nombre: str
    alias: tuple[str, ...]      # normalizados, ordenados de más largo a más corto
    familia: str                # "insumo" | "tratamiento" | "pago"


@dataclass
class Catalogo:
    entradas: list[EntradaCatalogo] = field(default_factory=list)

    @classmethod
    def desde_json(cls, data: dict) -> "Catalogo":
        entradas: list[EntradaCatalogo] = []
        for e in data.get("insumos", []):
            entradas.append(EntradaCatalogo(
                e["sku"], e["nombre"],
                tuple(sorted((limpiar(a) for a in e["alias"]), key=len, reverse=True)),
                "insumo"))
        for e in data.get("tratamientos", []):
            entradas.append(EntradaCatalogo(
                e["codigo"], e["nombre"],
                tuple(sorted((limpiar(a) for a in e["alias"]), key=len, reverse=True)),
                "tratamiento"))
        for e in data.get("metodos_pago", []):
            entradas.append(EntradaCatalogo(
                e["codigo"], e["codigo"].capitalize(),
                tuple(sorted((limpiar(a) for a in e["alias"]), key=len, reverse=True)),
                "pago"))
        return cls(entradas)

    def de_familia(self, familia: str) -> list[EntradaCatalogo]:
        return [e for e in self.entradas if e.familia == familia]

    def por_codigo(self, codigo: str) -> EntradaCatalogo | None:
        return next((e for e in self.entradas if e.codigo == codigo), None)


# ------------------------------------------------------------- coincidencias


@dataclass(frozen=True)
class Mencion:
    codigo: str
    nombre: str
    familia: str
    inicio: int
    fin: int


def menciones(tokens: list[str], catalogo: Catalogo,
              familias: tuple[str, ...] = ("insumo", "tratamiento", "pago")) -> list[Mencion]:
    """Todas las apariciones de una entrada del catálogo, con su posición.

    Los alias se prueban de más largo a más corto para que 'kit de
    blanqueamiento' gane sobre 'kit', y se marcan los tokens consumidos para
    que un mismo trozo de texto no cuente dos veces.
    """
    usados = [False] * len(tokens)
    out: list[Mencion] = []

    candidatos = [e for e in catalogo.entradas if e.familia in familias]
    # Alias más largos primero, globalmente: evita que 'resina' consuma el
    # texto de 'resina compuesta' de otra entrada.
    pares = sorted(
        ((e, a) for e in candidatos for a in e.alias),
        key=lambda p: len(p[1].split()), reverse=True,
    )

    for entrada, alias in pares:
        palabras = alias.split()
        n = len(palabras)
        for i in range(len(tokens) - n + 1):
            if any(usados[i:i + n]):
                continue
            if tokens[i:i + n] == palabras:
                for j in range(i, i + n):
                    usados[j] = True
                out.append(Mencion(entrada.codigo, entrada.nombre, entrada.familia, i, i + n))
    return sorted(out, key=lambda m: m.inicio)


# ----------------------------------------------------------------- extraer


@dataclass
class ItemDetectado:
    codigo: str
    nombre: str
    familia: str
    cantidad: int | None
    confianza: float
    fragmento: str


VENTANA = 4  # tokens hacia atrás donde se busca la cantidad de un producto


def extraer_items(texto: str, catalogo: Catalogo,
                  familias: tuple[str, ...] = ("insumo",)) -> list[ItemDetectado]:
    """Asocia cada producto mencionado con su cantidad.

    En español la cantidad va ANTES del sustantivo ("doce pastas"), así que se
    busca hacia atrás saltando palabras de relleno ("me quedan como unas tres
    agujas"). Si el mismo producto aparece dos veces, **gana la última**: es
    cómo suena una autocorrección ("tres... no, cuatro resinas").
    """
    tokens = limpiar(texto).split()
    nums = numeros_con_posicion(tokens)
    encontradas = menciones(tokens, catalogo, familias)

    # Un número no puede asignarse a dos productos distintos.
    consumidos: set[int] = set()
    detectados: dict[str, ItemDetectado] = {}

    for m in encontradas:
        cantidad: int | None = None
        confianza = 0.55  # producto reconocido pero sin cantidad clara
        # Candidatos: números que terminan antes del producto, dentro de la ventana.
        atras = [n for n in nums
                 if n.fin <= m.inicio
                 and m.inicio - n.fin <= VENTANA
                 and n.inicio not in consumidos
                 and all(t in RELLENO or t in CORRECCION or t in UNE
                         for t in tokens[n.fin:m.inicio])]
        if atras:
            elegido = atras[-1]  # el más cercano al producto
            cantidad, confianza = elegido.valor, 0.95
            consumidos.add(elegido.inicio)
        elif detectados.get(m.codigo) is None or detectados[m.codigo].cantidad is None:
            # Fallback: número inmediatamente después ("agujas, cuarenta").
            #
            # Solo si este producto todavía no tiene cantidad. Si no, un alias
            # repetido se roba el número del producto SIGUIENTE: en "cinco
            # anestesia carpule y cinco guantes", la mención de 'carpule' no
            # tiene número atrás y se llevaría el cinco de los guantes.
            adelante = [n for n in nums
                        if n.inicio >= m.fin
                        and n.inicio - m.fin <= 1
                        and n.inicio not in consumidos]
            if adelante:
                elegido = adelante[0]
                cantidad, confianza = elegido.valor, 0.85
                consumidos.add(elegido.inicio)

        ini_frag = max(0, m.inicio - VENTANA)
        item = ItemDetectado(
            codigo=m.codigo, nombre=m.nombre, familia=m.familia,
            cantidad=cantidad, confianza=confianza,
            fragmento=" ".join(tokens[ini_frag:m.fin]),
        )
        # Autocorrección: la última mención CON cantidad manda ("tres... no,
        # cuatro resinas"). Pero una mención sin cantidad nunca pisa a una que
        # sí la tenía: pasa cuando el producto se nombra dos veces con alias
        # distintos en la misma frase — "dos anestesias, o sea carpules".
        previo = detectados.get(m.codigo)
        if item.cantidad is not None or previo is None:
            detectados[m.codigo] = item

    return list(detectados.values())


def extraer_montos(texto: str) -> list[int]:
    """Números que aparecen junto a la palabra 'soles' — el dinero de la frase."""
    tokens = limpiar(texto).split()
    nums = numeros_con_posicion(tokens)
    out = []
    for n in nums:
        cola = tokens[n.fin:n.fin + 2]
        if any(t in {"soles", "sol", "s"} for t in cola):
            out.append(n.valor)
    return out


def extraer_pagos(texto: str, catalogo: Catalogo) -> list[str]:
    """Métodos de pago mencionados, en orden y sin repetir.

    Pueden ser VARIOS distintos —el pago mixto es real: *"mil en efectivo y
    mil quinientos por transferencia"*—, pero el mismo método nombrado dos
    veces sigue siendo uno solo: "transferencia del BCP" dispara los alias
    'transferencia' y 'bcp', que son el mismo código.
    """
    tokens = limpiar(texto).split()
    vistos: dict[str, None] = {}  # dict preserva el orden de inserción
    for m in menciones(tokens, catalogo, ("pago",)):
        vistos.setdefault(m.codigo)
    return list(vistos)
