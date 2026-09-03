# odontoflow-voice — canonical status and boundaries

> This is the **only** file added after promotion. Every other file in this
> repository is the contributor's, unchanged, and every commit below this one
> is theirs.

## Authorship

**This codebase was written by Alejandro Jesus Marcelo CH
(`AlejandroMarceloCh`).** All 5 commits of history are authored by them and are
preserved intact — never squashed, never rewritten, never force-pushed.

- Contributor upstream: https://github.com/AlejandroMarceloCh/odonto-voz (remote `alejandro`)
- Donor HEAD at promotion: `eb9a4ee0381972658fb8a9e717d4e056820d3d4e`
- Canonical remote: `git@github.com:MiguelAAR10/odontoflow-voice.git` (remote `origin`)

Do not attribute this code to a later author or agent. Provenance record:
`odontoflow-planning/CONTRIBUTIONS.md`.

## Role

**Canonical voice/language adapter** for OdontoFlow. A sibling service: its own
process, its own port (8000), its own dependency tree. It is not a submodule of
the backend or the frontend.

Workspace: `~/projects/portfolio/AI-EdgeRunners/odontoflow/`
(`odontoflow-planning` · `odontoflow-backend` · `odontoflow-frontend` · this repo)

## What this service must NOT do (V1)

It produces **structured drafts** that a human confirms. It is **not** a
business authority and must never directly create:

`Visit` · `ServiceExecution` · `ServiceConsumption` · `Charge` · `Payment` · `InventoryMovement`

The canonical OdontoFlow backend remains the **only** business authority.
Stock truth is `inventory_movements`; money truth is `charges` / `payments`.
A transcript is evidence of what was said, never proof of what happened —
which the original design already honours by asking the dentist to confirm.

## Data boundary — `backend/datos/catalogo.json`

The file is **kept intact**. It is two different assets and they are governed
differently:

### SYNTHETIC — do NOT promote to canonical clinic data

The SKUs, names and the implied price list are **invented for testing**, by the
author's own statement in the file's `_nota` and in the README: *"El catálogo
actual es **inventado** para poder probar. El bueno sale del tarifario de la
clínica."*

Never load these SKUs into `products` / `services` as if they were the clinic's
catalog. The real one comes from the clinic's tariff sheet.

Likewise, `CONTEO_PREVIO` in `backend/app/main.py` is initialised to **zero for
every supply**. `anterior` is a placeholder, not a prior count, so any
`diferencia` computed from it today is meaningless. The real prior is the
ledger balance (`GET /products/{id}/balance?location_id=…`).

### DOMAIN VOCABULARY — preserve, this is the valuable part

The **aliases** are genuine product knowledge: how Peruvian dentists and
patients actually speak. `colgate`→pasta, `carpule`/`carpules`→anestesia,
`suctor`→eyector, `braquets`/`cambio de ligas`→ortodoncia, `sacar la muela`/
`exodoncia`→extracción, `yapeo`/`yapeó`→yape, `bcp`/`interbank`/`bbva`→
transferencia, `izipay`/`pos`→tarjeta.

That cannot be derived from a tariff sheet — it comes from listening. The
README is right that *"the precision is won in `catalogo.json`, not in the
model."* Preserve every alias; re-key them onto real `products.id` /
`services.id` when the clinic's catalog arrives.

**V2 — Synthetic Clinic Configuration** will connect these aliases to an
editable configuration. Until then, changing the catalog is a data edit, not a
code change, exactly as the author designed it.

## Preserved assets — do not refactor for style

These carry the contribution's value and its tests. Change them only for a
stated functional reason, never to satisfy a formatting preference:

`backend/app/parser.py` · `backend/app/conversacion.py` ·
`backend/app/flujos.py` · `backend/app/transcriptor.py` ·
`backend/app/whatsapp.py` · `backend/datos/catalogo.json` · `auditar.py` ·
the donor docs (`README.md`, `CONTRATO-API.md`, `PETICIONES-A-MIGUEL.md`,
`PARA-ENCHUFAR-WHATSAPP.md`) · `backend/tests/`

`whatsapp.py` carries the author's own honesty notice: the Meta Graph API
payload shape was written from memory and is unverified. **Keep that notice.**

## Verified baseline (2026-09-02, at promotion)

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt   # clean, exit 0
.venv/bin/python -m pytest tests/ -q                                  # 54 passed, 0.89s
```

**54 tests PASS** — parser 21 · conversation 19 · api 9 (+parametrized). Python
3.12.3. No test touches audio or the network, which is why it runs in under a
second. The README says 45; the real count at HEAD is 54.

## Known platform limitation

`auditar.py` needs the **macOS `say`** binary to synthesise test audio, so it
**cannot run on Linux/WSL** and the audio/transcription path is **UNVERIFIED**
there. Its first two text checks do pass. It is platform-bound, not broken —
left unrepaired on purpose.

The author's latency figures (2.2 s mean / 3.6 s worst, `small`, CPU) are
**their measurements on Apple Silicon**. Do not quote them as OdontoFlow's
until re-measured here. The smallest fix is committing audio fixtures, which
also removes the TTS dependency and makes the audio assertions deterministic.

First boot downloads the Whisper model (~500 MB for `small`); `ODONTO_MODELO=tiny`
is enough for smoke-testing the transport.

## Frontend integration (V1)

The SPA consumes this service behind an opt-in flag. Both switches must allow it:

| `VITE_ENABLE_VOICE` | `VITE_USE_MOCKS` | behaviour |
|---|---|---|
| `false` (default) | anything | `/asistente` route not registered; no HTTP ever |
| `true` | `true` (default) | page renders, **no HTTP ever** |
| `true` | `false` | live, against `VITE_VOICE_URL` (default `http://127.0.0.1:8000`) |

Handoff: `odontoflow-frontend/.audit/voice-v1/voice-ui-port.md`.
