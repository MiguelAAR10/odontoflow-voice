# odontoflow-voice — DEVELOPMENT

## Qué es este repo

**El servicio de voz de OdontoFlow.** Escrito por **Alejandro Marcelo**
(`AlejandroMarceloCh`) — todos los 5 commits de historia debajo de este
archivo son suyos, preservados intactos. Servicio FastAPI standalone: su
propio proceso, su propio puerto (8000), cero base de datos compartida con el
resto del proyecto.

**Estado verificado (2026-09-03):** 54 tests PASS (su propia suite, sin
modificar). Detalle completo en `CANONICAL.md` de este repo y en
`odontoflow-planning/docs/handoffs/discovery/ODONTOFLOW_CTO_DISCOVERY_VERIFICATION.md`.

## Función de desarrollo

Transcribe audio (`faster-whisper`) y extrae datos estructurados con un
**parser por reglas, sin LLM en la decisión** — `app/parser.py` documenta por
qué: un modelo que alucina una cantidad produce un descuadre de inventario
real; una regla que falla se arregla agregando un alias.

Dos flujos: auditoría de inventario (dictado libre) y resumen de consulta
(5 preguntas guiadas). Ver `README.md` y `CONTRATO-API.md` para el contrato
completo.

## Cómo arrancar

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --port 8000       # primer arranque descarga ~500MB de Whisper

python -m pytest tests/ -q             # 54 tests, no tocan audio ni red
python ../auditar.py                   # end-to-end con audio real — requiere macOS (usa `say`)
```

## Frontera que nunca se cruza

Este servicio **nunca** escribe al backend canónico. Produce JSON — el humano
confirma, el backend de negocio decide. Si algún día se conecta:

```
voz → parser → JSON de negocio → [adaptador, no construido aún] → backend real
```

El adaptador no existe todavía. No lo construyas sin que alguien primero le dé
a este servicio una identidad real (un Principal con permisos, ver
`odontoflow-backend/app/iam/`) — sin eso, nada de lo que este servicio
"decida" puede escribirse legítimamente en la base de negocio.

## Lo que falta construir, en orden

1. **Hacer el harness de auditoría portable** — `auditar.py` depende de `say`
   (solo macOS). Grabar audios de prueba y commitearlos como fixtures
   resolvería esto para cualquier plataforma.
2. **Verificar `whatsapp.py` contra la documentación actual de Meta** — está
   escrito, pero el propio archivo dice que sus nombres de campo "fueron
   escritos de memoria" y deben confirmarse. Le falta además verificación de
   firma (`X-Hub-Signature-256`) e idempotencia por `message.id` — ninguna de
   las dos existe hoy.
3. **Registrar `whatsapp_router` en `app/main.py`** — está escrito pero no
   conectado (`include_router` no aparece).

## Datos — frontera sintética

`backend/datos/catalogo.json` tiene dos partes con reglas distintas: los SKUs
y precios son **inventados**, nunca deben pasar a ser catálogo real de una
clínica. Los **alias hablados** (`"colgate"→pasta`, `"carpule"→anestesia`) son
conocimiento de producto genuino — consérvalos si algún día se conecta a un
catálogo real.
