#!/usr/bin/env python3
"""Auditoría end-to-end del asistente de voz.

No prueba funciones: prueba el OBJETIVO. Levanta los dos flujos completos
contra el servidor real, con audio real, y verifica que el resultado sea el
que el médico espera. Si esto pasa, el sprint cumple.

    python3 auditar.py                 # usa audios generados con la voz del Mac
    python3 auditar.py --url http://…  # contra otro servidor

Sale con código 1 si algo no cumple, para poder encadenarlo en CI.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys
import tempfile
import time

import httpx

VERDE, ROJO, GRIS, FIN = "\033[32m", "\033[31m", "\033[90m", "\033[0m"

fallos: list[str] = []


def check(condicion: bool, descripcion: str, detalle: str = "") -> None:
    marca = f"{VERDE}✓{FIN}" if condicion else f"{ROJO}✗{FIN}"
    print(f"  {marca} {descripcion}")
    if detalle:
        print(f"      {GRIS}{detalle}{FIN}")
    if not condicion:
        fallos.append(descripcion)


def decir(texto: str, destino: pathlib.Path) -> pathlib.Path:
    """Genera un audio con la voz del sistema. Sin dependencias externas."""
    aiff = destino.with_suffix(".aiff")
    subprocess.run(["say", "-v", "Paulina", "-o", str(aiff), texto], check=True,
                   capture_output=True)
    subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y",
                    "-i", str(aiff), str(destino)], check=True)
    aiff.unlink()
    return destino


class Cliente:
    def __init__(self, url: str) -> None:
        self.url = url.rstrip("/")
        self.http = httpx.Client(timeout=180)
        self.sid: str | None = None
        self.latencias: list[tuple[float, float]] = []

    def texto(self, t: str) -> dict:
        r = self.http.post(f"{self.url}/mensaje",
                           json={"sesion_id": self.sid, "texto": t})
        r.raise_for_status()
        d = r.json()
        self.sid = d["sesion_id"]
        return d

    def audio(self, ruta: pathlib.Path) -> dict:
        with ruta.open("rb") as f:
            r = self.http.post(f"{self.url}/audio",
                               files={"archivo": (ruta.name, f, "audio/mp4")},
                               data={"sesion_id": self.sid or ""})
        r.raise_for_status()
        d = r.json()
        self.sid = d["sesion_id"]
        t = d["transcripcion"]
        self.latencias.append((t["segundos_audio"], t["segundos_proceso"]))
        print(f"      {GRIS}[{t['segundos_audio']}s audio → {t['segundos_proceso']}s] "
              f"«{t['texto']}»{FIN}")
        return d

    def nueva_sesion(self) -> None:
        self.sid = None


def ultimo(d: dict) -> dict:
    return d["mensajes"][-1]


def auditar_inventario(c: Cliente, tmp: pathlib.Path) -> None:
    print(f"\n{'═' * 70}\nFLUJO 1 · Auditoría de inventario\n{'═' * 70}")
    c.nueva_sesion()

    d = c.texto("hola")
    check(d["flujo"] is None and "inventario" in ultimo(d)["texto"].lower(),
          "El saludo ofrece los dos flujos")

    d = c.texto("quiero auditar el inventario de insumos")
    check(d["flujo"] == "inventario", "Elige inventario con lenguaje natural")

    print("\n  Dictado libre (3 audios, como recorriendo la estantería):")
    d = c.audio(decir("Quedan doce pastas, tres cepillos y cinco enjuagues.",
                      tmp / "inv1.m4a"))
    d = c.audio(decir("Tres, no, cuatro resinas. Y ocho eyectores.", tmp / "inv2.m4a"))
    d = c.audio(decir("Treinta y seis anestesias, cuarenta agujas y quince rollos de algodón.",
                      tmp / "inv3.m4a"))

    filas = {f["codigo"]: f["contado"] for f in ultimo(d)["adjunto"]["filas"]}
    esperado = {"PASTA-DENTAL": 12, "CEPILLO": 3, "ENJUAGUE": 5, "RESINA": 4,
                "EYECTOR": 8, "ANESTESIA": 36, "AGUJA": 40, "ALGODON": 15}
    malos = {k: (filas.get(k), v) for k, v in esperado.items() if filas.get(k) != v}
    check(not malos, f"Los {len(esperado)} insumos dictados quedaron con la cantidad correcta",
          "" if not malos else f"discrepancias (obtenido, esperado): {malos}")
    check(filas.get("RESINA") == 4,
          "La autocorrección «tres, no, cuatro» se resuelve a 4")

    d = c.texto("listo")
    a = ultimo(d)["adjunto"]
    check(not d["terminado"], "Con faltantes NO cierra solo: ofrece completarlos")
    check("faltaron" in ultimo(d)["texto"].lower(), "Nombra explícitamente qué faltó",
          ultimo(d)["texto"][:110])
    check(a["contados"] == len(esperado),
          f"Reporta {a['contados']} de {a['total']} contados")

    d = c.texto("igual")
    a = ultimo(d)["adjunto"]
    check(d["terminado"], "«igual» cierra dejando los faltantes como la última vez")
    check(all(f["contado"] is not None for f in a["filas"]),
          "Ningún insumo queda sin valor tras cerrar")
    check({f["codigo"]: f["contado"] for f in a["filas"]}["PASTA-DENTAL"] == 12,
          "Lo dictado no se pisa con el valor anterior")


def auditar_consulta(c: Cliente, tmp: pathlib.Path) -> None:
    print(f"\n{'═' * 70}\nFLUJO 2 · Resumen de consulta\n{'═' * 70}")
    c.nueva_sesion()

    d = c.texto("acabo de salir de una consulta y quiero hacer el resumen")
    check(d["flujo"] == "consulta", "Elige consulta con lenguaje natural")
    check("1 de 5" in ultimo(d)["texto"], "Arranca la primera de 5 preguntas",
          ultimo(d)["texto"])

    print("\n  Respuestas por voz:")
    for texto, archivo in [
        ("Juan Pérez", "c1.m4a"),
        ("Dos resinas y una limpieza.", "c2.m4a"),
        ("Dos anestesias y cuatro agujas.", "c3.m4a"),
        ("Ciento veinte soles, pagó con Yape.", "c4.m4a"),
    ]:
        d = c.audio(decir(texto, tmp / archivo))
    d = c.texto("ninguna")

    check(d["terminado"], "Cierra tras las 5 preguntas")
    a = ultimo(d)["adjunto"]
    check(a["tipo"] == "consulta", "Devuelve el JSON de negocio")
    check(a["total_bruto"] == 120, "Monto correcto", f"total_bruto={a['total_bruto']}")
    check(a["metodos_pago"] == ["yape"], "Método de pago correcto",
          f"metodos_pago={a['metodos_pago']}")

    consumo = {c_["codigo"]: c_["cantidad_consumida"] for c_ in a["consumo"]}
    check(consumo == {"ANESTESIA": 2, "AGUJA": 4}, "Insumos consumidos correctos",
          f"consumo={consumo}")
    servicios = {s["codigo"] for s in a["servicios"]}
    check(servicios == {"RESINA-SIMPLE", "PROFILAXIS"}, "Tratamientos correctos",
          f"servicios={servicios}")
    check(bool(a["paciente_ref"]), "Guarda la referencia del paciente",
          f"paciente_ref={a['paciente_ref']!r}")
    print(f"\n  {GRIS}JSON entregado al backend de negocio:{FIN}")
    print("  " + json.dumps(a, ensure_ascii=False, indent=2).replace("\n", "\n  "))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    args = ap.parse_args()

    c = Cliente(args.url)
    try:
        salud = c.http.get(f"{args.url}/salud").json()
    except Exception as exc:  # noqa: BLE001
        print(f"{ROJO}No hay servidor en {args.url}: {exc}{FIN}")
        print("Levántalo con:  uvicorn app.main:app --port 8000")
        return 1

    print(f"Servidor: {args.url} · {salud['insumos_en_catalogo']} insumos en catálogo")

    tmp = pathlib.Path(tempfile.mkdtemp())
    t0 = time.perf_counter()
    auditar_inventario(c, tmp)
    auditar_consulta(c, tmp)

    print(f"\n{'═' * 70}")
    if c.latencias:
        peor = max(p for _, p in c.latencias)
        media = sum(p for _, p in c.latencias) / len(c.latencias)
        check(peor < 15, f"Latencia aceptable: media {media:.1f}s, peor {peor:.1f}s",
              f"{len(c.latencias)} audios procesados")

    total = time.perf_counter() - t0
    if fallos:
        print(f"{ROJO}FALLA · {len(fallos)} comprobaciones no cumplen ({total:.0f}s){FIN}")
        for f in fallos:
            print(f"  {ROJO}·{FIN} {f}")
        return 1
    print(f"{VERDE}SPRINT CUMPLE · todas las comprobaciones pasan ({total:.0f}s){FIN}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
