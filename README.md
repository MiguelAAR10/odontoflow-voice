# OdontoFlow · Asistente de voz

El odontólogo dicta por audio y el sistema llena dos cosas que hoy se hacen a mano:

- **Auditoría de inventario** — dicta libre mientras recorre la estantería; el sistema le dice qué faltó.
- **Resumen de consulta** — cinco preguntas guiadas; salen paciente, tratamientos, insumos gastados y cobro.

Es el módulo de voz del reparto del equipo. Los otros dos —el backend de citas y el frontend— lo consumen por HTTP.

---

## Arrancar

Requisitos: **Python 3.10+**, **ffmpeg** (`brew install ffmpeg`).

```bash
git clone https://github.com/AlejandroMarceloCh/odonto-voz.git
cd odonto-voz/backend

python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

uvicorn app.main:app --port 8000
```

> **El primer arranque descarga el modelo de Whisper (~500 MB para `small`)** y tarda un minuto. Se descarga una sola vez y queda en la caché de HuggingFace. El servidor lo precarga en segundo plano al arrancar, así que el primer audio del día ya sale en tiempo normal.

Comprobar que vive: `curl localhost:8000/salud`

### Modelo y latencia

```bash
ODONTO_MODELO=small uvicorn app.main:app --port 8000   # por defecto
```

Medido sobre 7 audios reales en un Mac con Apple Silicon, modelo `small`, CPU: **2.2 s de media, 3.6 s el peor**. `large-v3` transcribe algo mejor pero multiplica el tiempo; para frases cortas de dominio cerrado `small` alcanza.

---

## Probar que funciona

```bash
# Tests: parser, máquina de conversación y API. No tocan audio ni red.
python -m pytest tests/ -q          # 45 tests

# Auditoría end-to-end: recorre los DOS flujos con audio real, generado
# con la voz del sistema. Verifica el objetivo, no las funciones.
cd .. && python auditar.py          # debe terminar en "SPRINT CUMPLE"
```

`auditar.py` comprueba lo que de verdad importa: que la autocorrección *"tres, no, cuatro"* resuelva a 4, que el inventario nombre lo que faltó y acepte *"igual"*, y que la consulta entregue el JSON de negocio con montos, pagos, insumos y tratamientos correctos.

---

## Cómo está armado

```
        navegador  ──►  POST /mensaje, POST /audio   ─┐
                                                       ├─►  procesar()  ─►  [Mensaje]
        WhatsApp   ──►  POST /whatsapp/webhook       ─┘
```

`procesar()` (`app/conversacion.py`) es **agnóstico de canal**: recibe una `Entrada` y devuelve `Mensaje`. No sabe si del otro lado hay un navegador, WhatsApp o un test. Por eso enchufar WhatsApp es un adaptador y no un rediseño — ver [PARA-ENCHUFAR-WHATSAPP.md](PARA-ENCHUFAR-WHATSAPP.md).

| Archivo | Qué hace |
|---|---|
| `app/parser.py` | Del habla a items: números en español, alias del catálogo, montos y medios de pago |
| `app/conversacion.py` | La máquina de estados de los dos flujos |
| `app/flujos.py` | Las preguntas, **como datos**: se cambian sin tocar el motor |
| `app/transcriptor.py` | faster-whisper local, modelo cargado una sola vez |
| `app/whatsapp.py` | Adaptador de WhatsApp Cloud API, desconectado |
| `app/main.py` | La API HTTP |
| `datos/catalogo.json` | Insumos, tratamientos y medios de pago **con sus alias hablados** |

### Dos decisiones que conviene entender

**Sin LLM, a propósito.** El parser es reglas contra un catálogo cerrado. Un modelo que alucina una cantidad produce un descuadre de inventario real, y cuando falla no se sabe por qué. Con reglas, un fallo se arregla agregando un alias. Coincide con la invariante que Miguel dejó escrita en su repo: *"LLMs never set prices, durations, slots or bookings"*.

**Todo local.** El audio lleva nombres de pacientes y diagnósticos: es PII sensible bajo la Ley 29733 y no sale de la máquina. Por eso no hay ruta a ninguna API de transcripción, aunque sería más rápida.

### Dónde se gana la precisión

En `datos/catalogo.json`, no en el modelo. Cada producto lleva **cómo lo dice la gente**, no cómo está en la factura:

```json
{ "sku": "PASTA-DENTAL", "nombre": "Pasta dental",
  "alias": ["pasta", "pastas", "crema dental", "colgate"] }
```

El catálogo actual es **inventado** para poder probar. El bueno sale del tarifario de la clínica. Cambiarlo no toca código.

---

## Lo que todavía no hace

- **No persiste.** Sesiones y conteo previo viven en memoria; al reiniciar se pierden. Cuando entre el PostgreSQL del backend de citas, salen de ahí.
- **No se autentica.** Cualquiera que llegue al puerto puede usarlo. Es una decisión de plataforma, no de este módulo.
- **Las 5 preguntas de consulta son un supuesto declarado.** La plantilla real de la clínica no ha llegado. Están en `app/flujos.py` como datos, justamente para eso.
- **WhatsApp está escrito pero apagado.** Lo que falta son cuatro trámites, no código.
