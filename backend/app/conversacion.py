"""Máquina de conversación. **Agnóstica de canal.**

Esta es la pieza que hace que enchufar WhatsApp sea un adaptador y no un
rediseño. El motor recibe `(sesion, Entrada)` y devuelve mensajes; no sabe si
del otro lado hay un navegador, WhatsApp o un test. Un canal nuevo solo tiene
que traducir su formato a `Entrada` y renderizar los `Mensaje` que salen.

    navegador ─┐
    WhatsApp  ─┼─► Entrada ─► procesar() ─► [Mensaje] ─► el canal los pinta
    tests     ─┘
"""
from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

from .flujos import (
    DISPARADORES, FLUJOS, INVENTARIO_APERTURA, PALABRAS_CIERRE, SALUDOS,
)
from .parser import (
    Catalogo, extraer_items, extraer_montos, extraer_pagos, limpiar,
)


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Mensaje:
    de: Literal["bot", "medico"]
    texto: str
    ts: str = field(default_factory=_ahora)
    adjunto: dict[str, Any] | None = None  # tabla de faltantes, resumen final…


@dataclass
class Entrada:
    """Lo que llega del canal. El audio ya viene transcrito."""
    texto: str
    es_audio: bool = False


@dataclass
class Sesion:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    flujo: str | None = None
    paso: int = 0
    datos: dict[str, Any] = field(default_factory=dict)
    conteo: dict[str, int] = field(default_factory=dict)      # inventario en curso
    mensajes: list[Mensaje] = field(default_factory=list)
    terminado: bool = False

    def decir(self, texto: str, adjunto: dict | None = None) -> Mensaje:
        m = Mensaje("bot", texto, adjunto=adjunto)
        self.mensajes.append(m)
        return m


# --------------------------------------------------------------- inventario


def _linea_base(catalogo: Catalogo, previo: dict[str, int] | None) -> dict[str, int]:
    """Lo que se espera contar: todo el catálogo de insumos."""
    return {e.codigo: (previo or {}).get(e.codigo, 0) for e in catalogo.de_familia("insumo")}


def _faltantes(catalogo: Catalogo, conteo: dict[str, int]) -> list[dict[str, Any]]:
    return [
        {"codigo": e.codigo, "nombre": e.nombre}
        for e in catalogo.de_familia("insumo")
        if e.codigo not in conteo
    ]


def _resumen_inventario(catalogo: Catalogo, conteo: dict[str, int],
                        previo: dict[str, int] | None) -> dict[str, Any]:
    previo = previo or {}
    filas = []
    for e in catalogo.de_familia("insumo"):
        contado = conteo.get(e.codigo)
        anterior = previo.get(e.codigo)
        filas.append({
            "codigo": e.codigo,
            "nombre": e.nombre,
            "anterior": anterior,
            "contado": contado,
            # RF del blueprint de Miguel: un ajuste es un MOVIMIENTO con motivo,
            # nunca una escritura directa sobre el stock.
            "diferencia": None if contado is None or anterior is None else contado - anterior,
            "estado": "pendiente" if contado is None else "contado",
        })
    return {"tipo": "inventario", "filas": filas,
            "contados": sum(1 for f in filas if f["estado"] == "contado"),
            "total": len(filas)}


# ----------------------------------------------------------------- consulta


def _resumen_consulta(datos: dict[str, Any]) -> dict[str, Any]:
    """El JSON que se entregaría al backend de negocio.

    Nombres de campo alineados al modelo de MediStock/OdontoFlow para que
    enchufe sin traductor: id_producto, cantidad_consumida, id_servicio…
    """
    return {
        "tipo": "consulta",
        "paciente_ref": datos.get("paciente"),
        "servicios": [
            {"codigo": i["codigo"], "nombre": i["nombre"], "cantidad": i.get("cantidad") or 1}
            for i in datos.get("tratamientos", [])
        ],
        "consumo": [
            {"codigo": i["codigo"], "nombre": i["nombre"], "cantidad_consumida": i.get("cantidad")}
            for i in datos.get("insumos", [])
        ],
        "total_bruto": (datos.get("cobro") or {}).get("monto"),
        "metodos_pago": (datos.get("cobro") or {}).get("pagos", []),
        "observaciones": datos.get("observaciones"),
    }


# ------------------------------------------------------------------ motor


# El médico puede contestar "1"/"2" o hablar. Lo primero es más rápido cuando
# ya conoce el flujo; lo segundo es lo natural la primera vez.
POR_NUMERO = {"1": "consulta", "2": "inventario"}


def _detectar_flujo(texto: str) -> str | None:
    t = limpiar(texto)
    if t in POR_NUMERO:
        return POR_NUMERO[t]
    # "opcion 2", "la 2", "dos"
    for numero, codigo in POR_NUMERO.items():
        if t in {f"opcion {numero}", f"la {numero}", f"el {numero}"}:
            return codigo
    if t in {"uno", "una"}:
        return "consulta"
    if t == "dos":
        return "inventario"
    for codigo, claves in DISPARADORES.items():
        if any(limpiar(k) in t for k in claves):
            return codigo
    return None


def _menu(sesion: Sesion) -> None:
    sesion.decir(
        "Hola. ¿Qué vamos a hacer hoy?\n"
        "1 · Resumen de una consulta que acabas de atender\n"
        "2 · Auditoría de inventario de insumos\n"
        "Responde con el número o dímelo con tus palabras."
    )


def procesar(sesion: Sesion, entrada: Entrada, catalogo: Catalogo,
             previo: dict[str, int] | None = None) -> list[Mensaje]:
    """Avanza la conversación un turno. Devuelve solo los mensajes nuevos."""
    desde = len(sesion.mensajes)
    sesion.mensajes.append(Mensaje("medico", entrada.texto))
    t = limpiar(entrada.texto)

    # --- sin flujo elegido todavía
    if sesion.flujo is None:
        elegido = _detectar_flujo(entrada.texto)
        if elegido is None:
            if t in SALUDOS or len(t.split()) <= 3:
                _menu(sesion)
            else:
                sesion.decir(
                    "No te entendí. ¿Es el resumen de una consulta o la auditoría de inventario?"
                )
            return sesion.mensajes[desde + 1:]

        sesion.flujo = elegido
        sesion.paso = 0
        if elegido == "inventario":
            sesion.decir(INVENTARIO_APERTURA)
        else:
            p = FLUJOS["consulta"].preguntas[0]
            sesion.decir(f"Perfecto, resumen de consulta.\n\n1 de 5 · {p.texto}")
        return sesion.mensajes[desde + 1:]

    # --- inventario: dictado libre
    if sesion.flujo == "inventario":
        if any(c in t for c in PALABRAS_CIERRE) and not entrada.es_audio:
            faltan = _faltantes(catalogo, sesion.conteo)
            resumen = _resumen_inventario(catalogo, sesion.conteo, previo)
            if faltan:
                nombres = ", ".join(f["nombre"] for f in faltan)
                sesion.decir(
                    f"Registré {resumen['contados']} de {resumen['total']} insumos. "
                    f"Te faltaron: {nombres}.\n"
                    "¿Los dicto ahora, o los dejo igual que la última vez? "
                    "Responde «igual» para dejarlos como estaban.",
                    adjunto=resumen)
            else:
                sesion.terminado = True
                sesion.decir(f"Listo. Los {resumen['total']} insumos quedaron actualizados.",
                             adjunto=resumen)
            return sesion.mensajes[desde + 1:]

        if t.startswith("igual") and not entrada.es_audio:
            previo = previo or {}
            for f in _faltantes(catalogo, sesion.conteo):
                sesion.conteo[f["codigo"]] = previo.get(f["codigo"], 0)
            sesion.terminado = True
            resumen = _resumen_inventario(catalogo, sesion.conteo, previo)
            sesion.decir("Hecho. Los que faltaban quedaron con el valor de la última vez.",
                         adjunto=resumen)
            return sesion.mensajes[desde + 1:]

        items = extraer_items(entrada.texto, catalogo, familias=("insumo",))
        nuevos = 0
        sin_cantidad = []
        for i in items:
            if i.cantidad is None:
                sin_cantidad.append(i.nombre)
                continue
            sesion.conteo[i.codigo] = i.cantidad  # el último dicho manda
            nuevos += 1

        resumen = _resumen_inventario(catalogo, sesion.conteo, previo)
        partes = [f"Anoté {nuevos} insumo{'s' if nuevos != 1 else ''}. "
                  f"Van {resumen['contados']} de {resumen['total']}."]
        if sin_cantidad:
            partes.append(f"No te entendí la cantidad de: {', '.join(sin_cantidad)}.")
        partes.append("Sigue cuando quieras, o escribe «listo».")
        sesion.decir(" ".join(partes), adjunto=resumen)
        return sesion.mensajes[desde + 1:]

    # --- consulta: preguntas guiadas
    preguntas = FLUJOS["consulta"].preguntas
    actual = preguntas[sesion.paso]

    if actual.extrae == "items":
        items = extraer_items(entrada.texto, catalogo, familias=actual.familias)
        sesion.datos[actual.campo] = [
            {"codigo": i.codigo, "nombre": i.nombre,
             "cantidad": i.cantidad, "confianza": i.confianza}
            for i in items
        ]
        if not items and actual.requerido:
            sesion.decir(
                f"No reconocí nada del catálogo ahí. {actual.ayuda}\n\n"
                f"{sesion.paso + 1} de {len(preguntas)} · {actual.texto}")
            return sesion.mensajes[desde + 1:]
    elif actual.extrae == "cobro":
        montos = extraer_montos(entrada.texto)
        pagos = extraer_pagos(entrada.texto, catalogo)
        sesion.datos[actual.campo] = {
            "monto": max(montos) if montos else None,
            "montos_detectados": montos,
            "pagos": pagos,
        }
        if not montos and actual.requerido:
            sesion.decir(
                f"No pillé el monto. {actual.ayuda}\n\n"
                f"{sesion.paso + 1} de {len(preguntas)} · {actual.texto}")
            return sesion.mensajes[desde + 1:]
    else:
        sesion.datos[actual.campo] = entrada.texto.strip()

    sesion.paso += 1
    if sesion.paso < len(preguntas):
        p = preguntas[sesion.paso]
        sesion.decir(f"{sesion.paso + 1} de {len(preguntas)} · {p.texto}")
    else:
        sesion.terminado = True
        resumen = _resumen_consulta(sesion.datos)
        sesion.decir("Listo, esto es lo que entendí. Revísalo y confirma.",
                     adjunto=resumen)
    return sesion.mensajes[desde + 1:]


def a_dict(sesion: Sesion) -> dict[str, Any]:
    d = asdict(sesion)
    d["mensajes"] = [asdict(m) for m in sesion.mensajes]
    return d
