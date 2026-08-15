"""Adaptador de WhatsApp Cloud API.

Este archivo es **el paso que falta**. El motor de conversación no cambia: este
adaptador solo traduce el formato de Meta a `Entrada` y devuelve los `Mensaje`
por la API de Meta. Es el mismo `procesar()` que usa el navegador.

    navegador  ──► /mensaje, /audio  ─┐
                                       ├─► procesar()  (sin cambios)
    WhatsApp   ──► /whatsapp/webhook ─┘

⚠️ AVISO DE HONESTIDAD
Los nombres de campo del payload de Meta y las rutas de la Graph API están
escritos de memoria y **hay que verificarlos contra la documentación vigente**
antes de confiar en ellos. Meta cambia el shape entre versiones. Lo que sí es
seguro es la forma del adaptador: recibir, transcribir, procesar, responder.

Para activarlo, en `main.py`:

    from .whatsapp import router as whatsapp_router
    app.include_router(whatsapp_router)

y definir las cuatro variables de entorno de abajo.
"""
from __future__ import annotations

import os
import pathlib
import tempfile

import httpx
from fastapi import APIRouter, HTTPException, Request, Response

from .conversacion import Entrada, Sesion, procesar
from .transcriptor import transcribir

# --- Las cuatro cosas que hay que tener. Sin esto, nada de acá funciona.
TOKEN = os.environ.get("WA_TOKEN", "")                 # token permanente de la app
PHONE_ID = os.environ.get("WA_PHONE_ID", "")           # id del número emisor
VERIFY_TOKEN = os.environ.get("WA_VERIFY_TOKEN", "")   # el que se pone en el panel de Meta
GRAPH = os.environ.get("WA_GRAPH", "https://graph.facebook.com/v21.0")

router = APIRouter(prefix="/whatsapp", tags=["whatsapp"])

# El teléfono ES la sesión: cada médico conversa desde su número.
SESIONES_WA: dict[str, Sesion] = {}


def _configurado() -> bool:
    return bool(TOKEN and PHONE_ID and VERIFY_TOKEN)


@router.get("/webhook")
def verificar(request: Request) -> Response:
    """Meta llama esto una vez al registrar el webhook y espera el challenge."""
    p = request.query_params
    if p.get("hub.mode") == "subscribe" and p.get("hub.verify_token") == VERIFY_TOKEN:
        return Response(content=p.get("hub.challenge", ""), media_type="text/plain")
    raise HTTPException(403, "verify token inválido")


async def _descargar_audio(media_id: str) -> pathlib.Path:
    """Dos saltos: el id da una URL firmada, y la URL da el binario."""
    cabeceras = {"Authorization": f"Bearer {TOKEN}"}
    async with httpx.AsyncClient(timeout=30) as c:
        meta = (await c.get(f"{GRAPH}/{media_id}", headers=cabeceras)).json()
        url = meta.get("url")
        if not url:
            raise HTTPException(502, f"Meta no devolvió url para el media {media_id}")
        binario = (await c.get(url, headers=cabeceras)).content

    destino = pathlib.Path(tempfile.mkdtemp()) / f"{media_id}.ogg"  # WhatsApp manda OGG/opus
    destino.write_bytes(binario)
    return destino


async def _responder(telefono: str, texto: str) -> None:
    async with httpx.AsyncClient(timeout=30) as c:
        await c.post(
            f"{GRAPH}/{PHONE_ID}/messages",
            headers={"Authorization": f"Bearer {TOKEN}"},
            json={"messaging_product": "whatsapp", "to": telefono,
                  "type": "text", "text": {"body": texto}},
        )


@router.post("/webhook")
async def entrante(request: Request, catalogo=None) -> dict:
    """Recibe un mensaje, lo procesa con el MISMO motor, y contesta."""
    if not _configurado():
        raise HTTPException(503, "faltan WA_TOKEN, WA_PHONE_ID o WA_VERIFY_TOKEN")

    from .main import CATALOGO, CONTEO_PREVIO  # import tardío: evita el ciclo

    cuerpo = await request.json()
    try:
        valor = cuerpo["entry"][0]["changes"][0]["value"]
        mensajes = valor.get("messages", [])
    except (KeyError, IndexError):
        return {"estado": "ignorado"}  # Meta manda también acuses de entrega

    for m in mensajes:
        telefono = m["from"]
        sesion = SESIONES_WA.setdefault(telefono, Sesion())

        if m.get("type") == "audio":
            ruta = await _descargar_audio(m["audio"]["id"])
            t = transcribir(ruta, CATALOGO)
            entrada = Entrada(t.texto, es_audio=True)
        elif m.get("type") == "text":
            entrada = Entrada(m["text"]["body"])
        else:
            await _responder(telefono, "Por ahora solo entiendo audios y texto.")
            continue

        for salida in procesar(sesion, entrada, CATALOGO, CONTEO_PREVIO):
            await _responder(telefono, salida.texto)

    return {"estado": "ok"}
