"""Tests de la API por el canal de texto.

No tocan audio a propósito: la transcripción se prueba aparte y con audio real.
Acá lo que se verifica es que el canal HTTP y el motor de conversación hablen
bien, que es lo que un adaptador de WhatsApp también tendrá que hacer.
"""
from fastapi.testclient import TestClient

from app.main import CATALOGO, app

cliente = TestClient(app)


def test_salud():
    r = cliente.get("/salud")
    assert r.status_code == 200
    assert r.json()["insumos_en_catalogo"] == len(CATALOGO.de_familia("insumo"))


def test_catalogo_lista_insumos_y_tratamientos():
    d = cliente.get("/catalogo").json()
    assert len(d["insumos"]) == len(CATALOGO.de_familia("insumo"))
    assert all({"codigo", "nombre", "anterior"} <= set(i) for i in d["insumos"])


def test_saludo_crea_sesion_y_ofrece_flujos():
    r = cliente.post("/mensaje", json={"texto": "hola"}).json()
    assert r["sesion_id"]
    assert r["flujo"] is None
    assert "inventario" in r["mensajes"][0]["texto"].lower()


def test_consulta_completa_devuelve_json_de_negocio():
    sid = cliente.post("/mensaje", json={"texto": "hola"}).json()["sesion_id"]
    guion = [
        "quiero el resumen de una consulta",
        "Juan Pérez",
        "dos resinas y una limpieza",
        "dos anestesias y cuatro agujas",
        "ciento veinte soles, pagó con Yape",
        "ninguna",
    ]
    r = {}
    for texto in guion:
        r = cliente.post("/mensaje", json={"sesion_id": sid, "texto": texto}).json()

    assert r["terminado"] is True
    adj = r["mensajes"][-1]["adjunto"]
    assert adj["tipo"] == "consulta"
    assert adj["total_bruto"] == 120
    assert adj["metodos_pago"] == ["yape"]
    assert {c["codigo"]: c["cantidad_consumida"] for c in adj["consumo"]} == {
        "ANESTESIA": 2, "AGUJA": 4}


def test_inventario_reporta_faltantes_y_acepta_igual():
    sid = cliente.post("/mensaje", json={"texto": "auditar inventario"}).json()["sesion_id"]
    cliente.post("/mensaje", json={"sesion_id": sid, "texto": "doce pastas y tres cepillos"})
    r = cliente.post("/mensaje", json={"sesion_id": sid, "texto": "listo"}).json()

    assert r["terminado"] is False, "con faltantes no se cierra solo"
    adj = r["mensajes"][-1]["adjunto"]
    assert adj["tipo"] == "inventario"
    assert adj["contados"] == 2

    r2 = cliente.post("/mensaje", json={"sesion_id": sid, "texto": "igual"}).json()
    assert r2["terminado"] is True
    filas = {f["codigo"]: f for f in r2["mensajes"][-1]["adjunto"]["filas"]}
    assert filas["PASTA-DENTAL"]["contado"] == 12
    assert all(f["contado"] is not None for f in filas.values())


def test_sesiones_no_se_pisan():
    a = cliente.post("/mensaje", json={"texto": "consulta"}).json()["sesion_id"]
    b = cliente.post("/mensaje", json={"texto": "inventario"}).json()["sesion_id"]
    assert a != b
    assert cliente.get(f"/sesion/{a}").json()["flujo"] == "consulta"
    assert cliente.get(f"/sesion/{b}").json()["flujo"] == "inventario"


def test_sesion_inexistente_da_404():
    assert cliente.get("/sesion/noexiste").status_code == 404
