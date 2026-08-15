"""Definición declarativa de los flujos.

Las preguntas viven acá como DATOS, no como código, por una razón concreta:
la plantilla real de Excel de la clínica todavía no llegó. Cuando llegue, se
cambian estas listas y no se toca la máquina de conversación ni el parser.

Cada pregunta declara qué extrae de la respuesta hablada:
  - `campo`      : nombre en el JSON de salida
  - `extrae`     : qué buscar ("texto" | "items" | "montos" | "pagos")
  - `familias`   : si extrae items, de qué familia del catálogo
  - `requerido`  : si el flujo no puede cerrarse sin esto
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Pregunta:
    campo: str
    texto: str
    extrae: str = "texto"
    familias: tuple[str, ...] = ()
    requerido: bool = True
    ayuda: str = ""


# ---------------------------------------------------------------- consulta

# SUPUESTO DECLARADO: estos 5 campos salen de lo que el médico describió en la
# reunión ("gasta insumos en una cita, necesita saber de qué trató la cita, y
# tiene los datos del paciente"). NO salen de la plantilla real, que aún no
# tenemos. Cambiar acá cuando llegue.
CONSULTA: tuple[Pregunta, ...] = (
    Pregunta(
        campo="paciente",
        texto="¿De qué paciente es la consulta? Dime el nombre o su DNI.",
        extrae="texto",
        ayuda="Ejemplo: «Juan Pérez» o «DNI 45610987».",
    ),
    Pregunta(
        campo="tratamientos",
        texto="¿Qué tratamientos le hiciste?",
        extrae="items",
        familias=("tratamiento",),
        ayuda="Ejemplo: «dos resinas y una limpieza».",
    ),
    Pregunta(
        campo="insumos",
        texto="¿Qué insumos gastaste?",
        extrae="items",
        familias=("insumo",),
        ayuda="Ejemplo: «dos anestesias, cuatro agujas y un rollo de algodón».",
    ),
    Pregunta(
        campo="cobro",
        texto="¿Cuánto se cobró y cómo pagó?",
        extrae="cobro",
        ayuda="Ejemplo: «ciento veinte soles, pagó con Yape».",
    ),
    Pregunta(
        campo="observaciones",
        texto="¿Alguna indicación u observación para la historia?",
        extrae="texto",
        requerido=False,
        ayuda="Si no hay nada, di «ninguna».",
    ),
)


# -------------------------------------------------------------- inventario

# El inventario NO se pregunta ítem por ítem: serían 50 preguntas y el médico
# abandona. Se dicta libre mientras recorre la estantería y el sistema reporta
# los faltantes al final. Eso fue explícito en el pedido.
INVENTARIO_APERTURA = (
    "Dale. Ve dictando mientras revisas la estantería, sin apuro y como te salga. "
    "Puedes mandar varios audios. Cuando termines, escribe «listo» y te digo qué faltó."
)

PALABRAS_CIERRE = {"listo", "termine", "terminé", "ya", "acabe", "acabé",
                   "fin", "eso es todo", "nada mas", "nada más"}


@dataclass
class DefinicionFlujo:
    codigo: str
    nombre: str
    preguntas: tuple[Pregunta, ...] = ()
    libre: bool = False


FLUJOS: dict[str, DefinicionFlujo] = {
    "consulta": DefinicionFlujo("consulta", "Resumen de consulta", CONSULTA),
    "inventario": DefinicionFlujo("inventario", "Auditoría de inventario", libre=True),
}

# Cómo el médico elige el flujo en lenguaje natural, sin menú numerado.
DISPARADORES: dict[str, tuple[str, ...]] = {
    "consulta": ("consulta", "cita", "resumen", "paciente", "atendi", "atendí",
                 "acabo de salir", "termine una", "terminé una"),
    "inventario": ("inventario", "insumo", "stock", "almacen", "almacén",
                   "auditar", "auditoria", "auditoría", "contar", "conteo"),
}

SALUDOS = {"hola", "buenas", "buenos dias", "buenos días", "buenas tardes",
           "buenas noches", "hey", "alo", "aló", "empezar", "inicio", "menu", "menú"}
