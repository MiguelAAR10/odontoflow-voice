"""Transcripción local con faster-whisper.

Dos decisiones que definen la latencia y la privacidad:

1. **El modelo se carga una sola vez** y vive en memoria del proceso. Cargarlo
   por request agrega decenas de segundos; el pedido era latencia baja.
2. **Todo corre local.** El audio lleva nombres de pacientes y diagnósticos:
   es PII sensible bajo la Ley 29733 y no puede salir de la máquina. Por eso
   no hay ruta a Groq ni a ninguna API, aunque sería más rápida.

El prompt de dominio se arma desde el catálogo, no a mano, para que no se
desincronice cuando entre un producto nuevo.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from .parser import Catalogo

# small ≈ 8× más rápido que large-v3 en CPU y suele bastar para frases cortas
# de dominio cerrado. Se cambia con ODONTO_MODELO sin tocar código.
MODELO = os.environ.get("ODONTO_MODELO", "small")
COMPUTE = os.environ.get("ODONTO_COMPUTE", "int8")

_modelo = None
_lock = threading.Lock()


def cargar_modelo():
    """Singleton perezoso y thread-safe. La primera llamada paga la carga."""
    global _modelo
    if _modelo is None:
        with _lock:
            if _modelo is None:
                from faster_whisper import WhisperModel
                _modelo = WhisperModel(MODELO, device="cpu", compute_type=COMPUTE)
    return _modelo


def prompt_de_dominio(catalogo: Catalogo) -> str:
    """Vocabulario denso, no una explicación: whisper corta a n_text_ctx/2."""
    insumos = [e.alias[0] for e in catalogo.de_familia("insumo")]
    tratam = [e.alias[0] for e in catalogo.de_familia("tratamiento")]
    pagos = [e.codigo for e in catalogo.de_familia("pago")]
    return (
        "Clínica dental en Lima. "
        f"Insumos: {', '.join(insumos)}. "
        f"Tratamientos: {', '.join(tratam)}. "
        f"Pagos: {', '.join(pagos)}. "
        "Montos en soles. Cantidades en números."
    )


def a_wav16k(origen: Path) -> Path:
    """whisper exige 16 kHz mono PCM. El celular nunca entrega eso."""
    destino = Path(tempfile.mkdtemp()) / "audio.wav"
    subprocess.run(
        ["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", str(origen),
         "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(destino)],
        check=True,
    )
    return destino


@dataclass
class Transcripcion:
    texto: str
    segundos_audio: float
    segundos_proceso: float
    modelo: str


def transcribir(ruta: Path, catalogo: Catalogo) -> Transcripcion:
    t0 = time.perf_counter()
    wav = a_wav16k(ruta)
    modelo = cargar_modelo()
    segmentos, info = modelo.transcribe(
        str(wav),
        language="es",
        initial_prompt=prompt_de_dominio(catalogo),
        vad_filter=True,          # descarta silencios: menos alucinación
        condition_on_previous_text=False,  # cada frase es independiente
    )
    texto = " ".join(s.text for s in segmentos).strip()
    return Transcripcion(
        texto=texto,
        segundos_audio=round(info.duration, 2),
        segundos_proceso=round(time.perf_counter() - t0, 2),
        modelo=MODELO,
    )
