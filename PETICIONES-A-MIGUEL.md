# Lo que el asistente de voz necesita del backend de citas

Miguel: esto sale de intentar enchufar mi módulo al tuyo. No es crítica — aparece justo porque soy el que va a escribir en `movimientos_stock`.

Primero, lo que está bien y no hay que tocar: tu **ledger de stock es el patrón correcto**. `001_stock_ledger_trigger.sql` con `movimientos_stock` append-only y el trigger que registra la SALIDA por cada consumo es exactamente como debe ser, y tu propio análisis de por qué el legacy fallaba (la doble escritura sobre `stock_actual`) es el mejor documento del repo. Sobre eso van estas dos peticiones.

---

## 1. Falta el tipo `AJUSTE` · bloqueante

Hoy:

```sql
tipo_movimiento VARCHAR(10) NOT NULL CHECK (tipo_movimiento IN ('ENTRADA', 'SALIDA'))
```

**Con ese CHECK, mi módulo no puede escribir un conteo físico.** Un conteo que da 12 cuando el sistema dice 15 no es una SALIDA: nadie consumió esas 3. Es un ajuste contra lo esperado, y la diferencia es justamente el dato que interesa.

Y encaja con tu propia regla del blueprint:

> *"Every stock change, including corrections, is a movement row with a reason, full stop."*

Un ajuste **es** un cambio de stock. Hoy no tiene fila posible.

Propuesta:

```sql
tipo_movimiento CHECK (tipo_movimiento IN ('ENTRADA', 'SALIDA', 'AJUSTE'))
cantidad_esperada NUMERIC(10,2)   -- lo que el sistema creía; NULL salvo en AJUSTE
```

Guardar la esperada además de la contada permite reconstruir la merma sin recalcular todo el ledger.

## 2. Devolver el campo `motivo`

En `003_sp_register_entrada.sql` lo quitaste a propósito:

> *"Se elimina el parámetro p_motivo. La función es ahora más simple."*

Para entradas puras es defendible. Para ajustes es fatal: **sin motivo no se distingue merma de robo, de error de conteo, ni de traspaso entre sedes.** Y ese es exactamente el análisis que el dueño hace hoy a mano — cuando falta producto, rastrea contra las ventas y decide de quién es la responsabilidad.

Propuesta: `motivo VARCHAR(30)` con valores cerrados (`CONTEO`, `MERMA`, `ROBO`, `VENCIMIENTO`, `TRASPASO`, `CORRECCION`), obligatorio solo cuando `tipo_movimiento = 'AJUSTE'`.

## 3. Quién hizo el movimiento

`movimientos_stock` no registra actor. Es el dato que el dueño usa: *"¿a quién se hace responsable? A la secretaria, porque ella es la única que vende"*. Sin eso el sistema no puede sostener esa conversación.

Como ya tienes `Principal` y `ExecutionContext`, lo natural es un FK al principal, y así un dictado por voz queda atribuido al odontólogo que lo mandó.

## 4. `id_sede` · no urgente, pero condiciona el modelo

Ninguna tabla tiene sede. La clínica tiene tres —pronto cuatro— y **se prestan insumos entre ellas**: el dueño lo explicó en la reunión, y aclaró que la devolución es en producto, no en dinero.

Eso no es una columna extra: cambia la clave de todo el stock y pide un tipo de movimiento `TRASPASO` con origen y destino. Tu `Location` ya es ciudadano de primera clase en scheduling; el inventario debería heredarlo desde el diseño, no después.

---

## Mientras tanto

Mi módulo entrega el JSON y no escribe en ninguna base. El contrato está en [CONTRATO-API.md](CONTRATO-API.md); el adjunto de inventario ya trae `anterior`, `contado` y `diferencia` por producto, que es exactamente lo que necesita una fila de `AJUSTE`.

Cuando existan el tipo y el motivo, conectar es un `POST` desde mi lado.
