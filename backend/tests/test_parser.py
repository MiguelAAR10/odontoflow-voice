"""Tests del parser de dominio. Sin red, sin modelo, sin audio: puro texto."""
import json
import pathlib

import pytest

from app.parser import (
    Catalogo, extraer_items, extraer_montos, extraer_pagos, numeros_en,
)

DATOS = pathlib.Path(__file__).resolve().parents[1] / "datos" / "catalogo.json"


@pytest.fixture(scope="module")
def catalogo() -> Catalogo:
    return Catalogo.desde_json(json.loads(DATOS.read_text(encoding="utf-8")))


# ------------------------------------------------------------------ números

@pytest.mark.parametrize("texto,esperado", [
    ("Quedan doce pastas, tres cepillos y cinco enjuagues.", [3, 5, 12]),
    ("Dos resinas en pieza veintiséis y veintisiete, ciento veinte soles.", [2, 26, 27, 120]),
    ("Prótesis, mil doscientos soles.", [1200]),
    ("Treinta y seis anestesias.", [36]),
    ("Doscientos setenta soles.", [270]),
    ("Se acabó el flúor. Cero.", [0]),
    ("Cuatrocientos cincuenta soles.", [450]),
    ("Dos mil quinientos soles, mil en efectivo y mil quinientos por transferencia.",
     [1000, 1500, 2500]),
])
def test_numeros_en_palabras(texto, esperado):
    assert sorted(numeros_en(texto).elements()) == esperado


def test_veintiseis_y_veintisiete_son_dos_numeros():
    """El bug que rompió la primera versión: 26 y 27 no son 53."""
    assert sorted(numeros_en("pieza veintiséis y veintisiete").elements()) == [26, 27]


# -------------------------------------------------------------------- items

def test_cantidad_antes_del_producto(catalogo):
    items = extraer_items("Quedan doce pastas, tres cepillos y cinco enjuagues.", catalogo)
    got = {i.codigo: i.cantidad for i in items}
    assert got == {"PASTA-DENTAL": 12, "CEPILLO": 3, "ENJUAGUE": 5}
    assert all(i.confianza >= 0.9 for i in items)


def test_relleno_no_rompe_la_asociacion(catalogo):
    """'me quedan como unas tres agujas' — el relleno se salta."""
    items = extraer_items("Me quedan como unas tres agujas.", catalogo)
    assert {i.codigo: i.cantidad for i in items} == {"AGUJA": 3}


def test_autocorreccion_gana_el_ultimo(catalogo):
    """'tres... no, cuatro resinas' debe dar 4, no 3 ni las dos."""
    items = extraer_items("Tres... no, cuatro resinas. Y ocho eyectores.", catalogo)
    got = {i.codigo: i.cantidad for i in items}
    assert got["RESINA"] == 4
    assert got["EYECTOR"] == 8


def test_correccion_repitiendo_el_producto(catalogo):
    """El caso que describió el médico: repite el producto al corregirse."""
    items = extraer_items("Me gastó como dos agujas, no, dos no, unas cuatro agujas.", catalogo)
    assert {i.codigo: i.cantidad for i in items} == {"AGUJA": 4}


def test_producto_sin_cantidad_baja_la_confianza(catalogo):
    items = extraer_items("Se acabaron los cepillos.", catalogo)
    assert len(items) == 1
    assert items[0].cantidad is None
    assert items[0].confianza < 0.7


def test_alias_largo_gana_sobre_corto(catalogo):
    """'kit de blanqueamiento' no debe partirse en 'kit'."""
    items = extraer_items("Dos kits de blanqueamiento.", catalogo)
    assert [i.codigo for i in items] == ["KIT-BLANQ"]


def test_un_numero_no_se_reparte_entre_dos_productos(catalogo):
    items = extraer_items("Cinco cepillos, pastas.", catalogo)
    got = {i.codigo: i.cantidad for i in items}
    assert got["CEPILLO"] == 5
    assert got["PASTA-DENTAL"] is None


def test_cantidad_despues_del_producto(catalogo):
    items = extraer_items("Agujas cuarenta.", catalogo)
    assert {i.codigo: i.cantidad for i in items} == {"AGUJA": 40}


def test_texto_sin_catalogo_no_inventa(catalogo):
    assert extraer_items("El paciente refiere dolor y molestia.", catalogo) == []


# ------------------------------------------------------------ montos y pago

def test_monto_solo_cuando_dice_soles(catalogo):
    """'pieza veintiséis' no es dinero; 'ciento veinte soles' sí."""
    assert extraer_montos("Dos resinas en pieza veintiséis, ciento veinte soles.") == [120]


def test_pago_mixto_devuelve_dos_metodos(catalogo):
    pagos = extraer_pagos(
        "Dos mil quinientos soles, mil en efectivo y mil quinientos por transferencia.",
        catalogo)
    assert set(pagos) == {"efectivo", "transferencia"}


def test_yape_y_plin_se_reconocen(catalogo):
    assert extraer_pagos("pagó con Yape", catalogo) == ["yape"]
    assert extraer_pagos("pagó con Plin", catalogo) == ["plin"]


def test_banco_cuenta_como_transferencia(catalogo):
    assert extraer_pagos("transferencia del BCP", catalogo) == ["transferencia"]


# ----------------------------------------------------------- tratamientos

def test_tratamientos_se_extraen_por_familia(catalogo):
    items = extraer_items("Control de ortodoncia, cambio de ligas.", catalogo,
                          familias=("tratamiento",))
    assert [i.codigo for i in items] == ["ORTO-CONTROL"]


def test_alias_repetido_no_borra_la_cantidad(catalogo):
    """'dos anestesias, o sea carpules' — la segunda mención del mismo
    producto, sin cantidad, no debe pisar a la primera."""
    items = extraer_items("Dos anestesias, o sea carpules.", catalogo)
    assert {i.codigo: i.cantidad for i in items} == {"ANESTESIA": 2}


def test_alias_repetido_no_roba_el_numero_del_siguiente(catalogo):
    """'cinco anestesias, o sea carpules, y cinco guantes': el segundo alias
    de anestesia no puede quedarse con el cinco que era de los guantes."""
    items = extraer_items("cinco anestesia carpule y cinco guantes", catalogo)
    got = {i.codigo: i.cantidad for i in items}
    assert got == {"ANESTESIA": 5, "GUANTES": 5}
