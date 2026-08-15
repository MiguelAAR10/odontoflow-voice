# Contrato de la API

Para Leo (que programa contra esto) y para Miguel (que va a recibir estos JSON).

Base por defecto: `http://127.0.0.1:8000`. CORS abierto a `:5173`.

---

## Endpoints

### `GET /salud`
```json
{ "estado": "ok", "insumos_en_catalogo": 12 }
```

### `GET /catalogo`
Para pintar la tabla de inventario esperada antes de que el médico dicte nada.
```json
{
  "insumos": [{ "codigo": "PASTA-DENTAL", "nombre": "Pasta dental", "anterior": 0 }],
  "tratamientos": [{ "codigo": "PROFILAXIS", "nombre": "Profilaxis / limpieza" }]
}
```

### `POST /mensaje` — canal de texto
```json
{ "sesion_id": "a1b2c3d4e5f6", "texto": "listo" }
```
`sesion_id` es opcional: si no viene, se crea una sesión nueva y se devuelve.

### `POST /audio` — canal de voz
`multipart/form-data` con `archivo` (el blob) y `sesion_id` (opcional).
Acepta cualquier formato que lea ffmpeg: `webm` del navegador, `m4a` del celular, `ogg` de WhatsApp.

### `GET /sesion/{id}` · `POST /sesion/{id}/reiniciar`
Estado completo de una sesión, y arrancar de cero.

---

## Respuesta (igual para `/mensaje` y `/audio`)

```ts
{
  sesion_id: string,
  flujo: "consulta" | "inventario" | null,   // null = todavía eligiendo
  terminado: boolean,
  mensajes: {
    de: "bot" | "medico",
    texto: string,
    ts: string,                 // ISO 8601 UTC
    adjunto: Adjunto | null
  }[],
  transcripcion: {              // solo en /audio
    texto: string,
    segundos_audio: number,
    segundos_proceso: number,   // pintarlo: da confianza de que no se colgó
    modelo: string
  } | null
}
```

`mensajes` trae **solo los nuevos** de este turno, no el historial. El historial completo está en `GET /sesion/{id}`.

---

## Los dos `adjunto`

### Inventario
Llega en cada turno del flujo de inventario, para poder pintar la tabla en vivo.

```ts
{
  tipo: "inventario",
  contados: number,
  total: number,
  filas: {
    codigo: string,
    nombre: string,
    anterior: number | null,     // el conteo de la vez pasada
    contado: number | null,      // null = todavía no lo dictó
    diferencia: number | null,   // contado - anterior
    estado: "contado" | "pendiente"
  }[]
}
```

### Consulta
Llega una sola vez, al cerrar el flujo. **Este es el JSON que va al backend de negocio.**

```ts
{
  tipo: "consulta",
  paciente_ref: string,          // texto crudo: "Juan Pérez" o "DNI 45610987"
  servicios:  { codigo, nombre, cantidad }[],
  consumo:    { codigo, nombre, cantidad_consumida }[],
  total_bruto: number | null,
  metodos_pago: string[],        // varios: el pago mixto es real
  observaciones: string | null
}
```

Los nombres de campo salen del modelo de MediStock/OdontoFlow (`cantidad_consumida`, `total_bruto`, `id_servicio`) para que enchufe sin traductor en el medio.

---

## Reglas de la conversación que el front debe respetar

1. **`listo` e `igual` se escriben, no se dictan.** Cerrar el inventario y aceptar los valores anteriores son comandos de texto; el motor los ignora si vienen marcados como audio. Por eso la vista necesita input de texto además del micrófono.
2. **Con faltantes, el inventario NO cierra solo.** Devuelve `terminado: false` y ofrece completarlos. Cerrarlo a la fuerza pierde datos.
3. **El médico puede mandar varios audios seguidos.** El conteo se acumula y **lo último dicho pisa a lo anterior**: así funciona corregirse.
4. **Una sesión = un flujo.** Para cambiar de flujo hay que reiniciar.

---

## Lo que este módulo espera del backend de citas

Para poder escribir un conteo físico, `movimientos_stock` necesita dos cosas que hoy no tiene:

1. **Un tercer tipo de movimiento, `AJUSTE`.** Hoy el `CHECK` solo admite `ENTRADA` y `SALIDA`. Un conteo que da 12 cuando el sistema dice 15 no es una salida: es un ajuste contra lo esperado, y hay que guardar también la cantidad esperada.
2. **El campo `motivo`, que se eliminó a propósito** (*"la función es ahora más simple"*). Sin él no se distingue merma de robo, de error de conteo, ni de traspaso entre sedes.

Y, mirando más adelante, `id_sede`: la clínica tiene tres sedes con préstamos de insumos entre ellas.
