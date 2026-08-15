# Para enchufar WhatsApp falta esto

Respuesta corta: **el código ya está.** Lo que falta no se programa, se gestiona.

El motor de conversación es agnóstico de canal desde el diseño. El navegador y WhatsApp entran por la misma función `procesar()`; lo único distinto es quién traduce el formato.

```
navegador  ──► /mensaje, /audio     ─┐
                                      ├─► procesar()  ← no cambia una línea
WhatsApp   ──► /whatsapp/webhook    ─┘
```

El adaptador está escrito en `backend/app/whatsapp.py`: verificación del webhook, descarga del audio en dos saltos, transcripción y respuesta. Está desconectado a propósito — se activa con dos líneas en `main.py`.

---

## Los 4 pasos que faltan, en orden

### 1. Cuenta de Meta Business verificada · días, no horas

Es el que más tarda y no depende de nosotros. Requiere documentos de la empresa y aprobación de Meta. **Empezarlo ya**, aunque el resto no esté.

### 2. Número de WhatsApp Business dedicado

Un número que **deja de poder usarse en la app normal de WhatsApp**. Esto no es un detalle técnico, es una decisión del negocio: hoy el dueño responde personalmente desde su celular, y ese número no puede ser el mismo. Para el flujo del médico (inventario y consultas) conviene un número aparte de todos modos: es un canal interno, no de pacientes.

De ahí salen `WA_PHONE_ID` y el token permanente `WA_TOKEN`.

### 3. URL pública HTTPS para el webhook · **el conflicto real**

Meta necesita hacer una petición **entrante** al servidor. Y el requisito del cliente es que la máquina viva dentro de la clínica y no sea alcanzable desde internet.

Tres salidas, ya analizadas:

| Salida | Cómo | Qué cuesta |
|---|---|---|
| **Túnel de salida** (Cloudflare Tunnel) | Conexión saliente desde la clínica, sin abrir puertos ni exponer IP | Mete un tercero en el camino. Hay que decírselo al cliente: es justo su punto sensible |
| **Relay propio** (VPS mínimo) ✅ | El VPS recibe el webhook y la clínica lo consulta por polling saliente | Un VPS y una pieza más que mantener. Mantiene la promesa de "nadie de afuera toca mis datos" |
| **Solo enviar** | Sin webhook | El médico no puede contestar. **Mata el producto**: los dos flujos son conversación |

**Recomendación: relay propio.** Es el único que no obliga a explicarle al cliente por qué su servidor habla con Cloudflare.

### 4. Ventana de 24 horas y plantillas

Como **el médico inicia la conversación**, cae en "service conversation" y se puede responder libremente durante 24 h sin plantilla aprobada. Eso simplifica mucho: **no hacen falta plantillas para este módulo.**

Sí harían falta si el sistema quisiera escribirle primero al médico (por ejemplo, un recordatorio de "toca inventario de fin de mes"). Ese caso sí necesita plantilla aprobada, y conviene pedirla desde ahora porque la aprobación tarda.

---

## Una vez que existan esas cuatro cosas

```bash
export WA_TOKEN="…"          # token permanente de la app de Meta
export WA_PHONE_ID="…"       # id del número emisor
export WA_VERIFY_TOKEN="…"   # inventado por nosotros; se pega en el panel de Meta
```

Y en `backend/app/main.py`:

```python
from .whatsapp import router as whatsapp_router
app.include_router(whatsapp_router)
```

Registrar `https://<dominio>/whatsapp/webhook` en el panel de Meta, suscribirse al evento `messages`, y ya.

---

## Lo que hay que verificar antes de confiar en el adaptador

`whatsapp.py` está escrito **de memoria sobre la Graph API**. Los nombres de campo del payload (`entry[0].changes[0].value.messages[]`, `audio.id`) y las rutas hay que **contrastarlos con la documentación vigente de Meta** — cambian entre versiones. Lo que no cambia es la forma del adaptador: recibir, transcribir, procesar, responder.

También sin probar contra Meta real:
- **Formato de audio.** WhatsApp manda OGG/Opus. `ffmpeg` lo convierte sin problema, pero conviene confirmarlo con un audio real.
- **Reintentos.** Si Meta no recibe 200 rápido, reintenta y el médico recibe la respuesta dos veces. La solución es responder 200 de inmediato y procesar en segundo plano, más una clave de idempotencia por `message.id`. **Hoy no está.** Es la primera mejora cuando el canal exista.
