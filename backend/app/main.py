"""API del asistente de voz de OdontoFlow.

El canal web de hoy y el WhatsApp de mañana entran por el MISMO motor: los
endpoints solo traducen su formato a `Entrada` y devuelven los `Mensaje` que
salen. Ver `adaptadores.md` para el paso que falta.
"""
from __future__ import annotations

import json
import pathlib
import threading
import shutil
import tempfile
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .conversacion import Entrada, Mensaje, Sesion, a_dict, procesar
from .parser import Catalogo
from .transcriptor import Transcripcion, transcribir

DATOS = pathlib.Path(__file__).resolve().parents[1] / "datos"
CATALOGO = Catalogo.desde_json(json.loads((DATOS / "catalogo.json").read_text(encoding="utf-8")))

# Estado en memoria. Es un prototipo: al reiniciar se pierde, y está bien.
# Cuando entre el backend de Miguel, las sesiones y el conteo previo salen de
# PostgreSQL y este diccionario desaparece.
SESIONES: dict[str, Sesion] = {}
CONTEO_PREVIO: dict[str, int] = {e.codigo: 0 for e in CATALOGO.de_familia("insumo")}

@asynccontextmanager
async def ciclo_de_vida(_: FastAPI):
    """Carga el modelo al arrancar, en un hilo aparte.

    Sin esto, el PRIMER audio del día paga ~50 s de carga y el médico cree que
    se colgó. Con esto, el servidor tarda más en estar listo pero la primera
    transcripción ya sale en tiempo normal. En régimen: ~2.7 s para 5 s de audio.
    """
    from .transcriptor import cargar_modelo

    hilo = threading.Thread(target=cargar_modelo, daemon=True)
    hilo.start()
    yield


app = FastAPI(title="OdontoFlow · Asistente de voz", version="0.1.0",
              lifespan=ciclo_de_vida)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _sesion(sesion_id: str | None) -> Sesion:
    if sesion_id and sesion_id in SESIONES:
        return SESIONES[sesion_id]
    s = Sesion()
    SESIONES[s.id] = s
    return s


def _respuesta(sesion: Sesion, nuevos: list[Mensaje],
               transcripcion: Transcripcion | None = None) -> dict:
    return {
        "sesion_id": sesion.id,
        "flujo": sesion.flujo,
        "terminado": sesion.terminado,
        "mensajes": [
            {"de": m.de, "texto": m.texto, "ts": m.ts, "adjunto": m.adjunto}
            for m in nuevos
        ],
        "transcripcion": None if transcripcion is None else {
            "texto": transcripcion.texto,
            "segundos_audio": transcripcion.segundos_audio,
            "segundos_proceso": transcripcion.segundos_proceso,
            "modelo": transcripcion.modelo,
        },
    }


@app.get("/salud")
def salud() -> dict:
    return {"estado": "ok", "insumos_en_catalogo": len(CATALOGO.de_familia("insumo"))}


@app.get("/catalogo")
def catalogo() -> dict:
    """Lo consume el front para pintar la tabla de inventario esperada."""
    return {
        "insumos": [
            {"codigo": e.codigo, "nombre": e.nombre, "anterior": CONTEO_PREVIO.get(e.codigo)}
            for e in CATALOGO.de_familia("insumo")
        ],
        "tratamientos": [
            {"codigo": e.codigo, "nombre": e.nombre}
            for e in CATALOGO.de_familia("tratamiento")
        ],
    }


class MensajeTexto(BaseModel):
    sesion_id: str | None = None
    texto: str


@app.post("/mensaje")
def mensaje(cuerpo: MensajeTexto) -> dict:
    """Canal de texto. Es el mismo motor que usa el audio."""
    s = _sesion(cuerpo.sesion_id)
    nuevos = procesar(s, Entrada(cuerpo.texto), CATALOGO, CONTEO_PREVIO)
    return _respuesta(s, nuevos)


@app.post("/audio")
async def audio(archivo: UploadFile = File(...), sesion_id: str | None = Form(None)) -> dict:
    """Canal de voz: transcribe y mete el texto por el mismo motor."""
    if not archivo.filename:
        raise HTTPException(400, "archivo sin nombre")

    tmp = pathlib.Path(tempfile.mkdtemp()) / archivo.filename
    with tmp.open("wb") as f:
        shutil.copyfileobj(archivo.file, f)

    try:
        t = transcribir(tmp, CATALOGO)
    except Exception as exc:  # noqa: BLE001 — el canal necesita un mensaje, no un stack
        raise HTTPException(500, f"no se pudo transcribir: {exc}") from exc

    s = _sesion(sesion_id)
    nuevos = procesar(s, Entrada(t.texto, es_audio=True), CATALOGO, CONTEO_PREVIO)
    return _respuesta(s, nuevos, t)


@app.get("/sesion/{sesion_id}")
def sesion(sesion_id: str) -> dict:
    if sesion_id not in SESIONES:
        raise HTTPException(404, "sesión no encontrada")
    return a_dict(SESIONES[sesion_id])


@app.post("/sesion/{sesion_id}/reiniciar")
def reiniciar(sesion_id: str) -> dict:
    SESIONES.pop(sesion_id, None)
    s = _sesion(None)
    return {"sesion_id": s.id}
