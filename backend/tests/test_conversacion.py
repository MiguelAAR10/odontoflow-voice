"""Tests de la máquina de conversación. Sin audio ni red: se inyecta texto."""
import json
import pathlib

import pytest

from app.conversacion import Entrada, Sesion, procesar
from app.parser import Catalogo

DATOS = pathlib.Path(__file__).resolve().parents[1] / "datos" / "catalogo.json"


@pytest.fixture(scope="module")
def catalogo() -> Catalogo:
    return Catalogo.desde_json(json.loads(DATOS.read_text(encoding="utf-8")))


def hablar(sesion, texto, catalogo, previo=None, audio=False):
    return procesar(sesion, Entrada(texto, es_audio=audio), catalogo, previo)


# ------------------------------------------------------------------- menú

def test_saludo_ofrece_los_dos_flujos(catalogo):
    s = Sesion()
    out = hablar(s, "hola", catalogo)
    assert len(out) == 1
    assert "consulta" in out[0].texto.lower()
    assert "inventario" in out[0].texto.lower()
    assert s.flujo is None


def test_elige_flujo_con_lenguaje_natural(catalogo):
    s = Sesion()
    hablar(s, "hola", catalogo)
    hablar(s, "acabo de salir de una consulta y quiero hacer el resumen", catalogo)
    assert s.flujo == "consulta"


def test_elige_inventario(catalogo):
    s = Sesion()
    hablar(s, "quiero auditar el inventario de insumos", catalogo)
    assert s.flujo == "inventario"


# --------------------------------------------------------------- consulta

def test_consulta_recorre_las_cinco_preguntas(catalogo):
    s = Sesion()
    hablar(s, "resumen de consulta", catalogo)
    hablar(s, "Juan Pérez", catalogo)
    hablar(s, "dos resinas y una limpieza", catalogo)
    hablar(s, "dos anestesias y cuatro agujas", catalogo)
    hablar(s, "ciento veinte soles, pagó con Yape", catalogo)
    out = hablar(s, "ninguna", catalogo)

    assert s.terminado
    resumen = out[-1].adjunto
    assert resumen["tipo"] == "consulta"
    assert resumen["paciente_ref"] == "Juan Pérez"
    assert resumen["total_bruto"] == 120
    assert resumen["metodos_pago"] == ["yape"]

    consumo = {c["codigo"]: c["cantidad_consumida"] for c in resumen["consumo"]}
    assert consumo == {"ANESTESIA": 2, "AGUJA": 4}
    assert {sv["codigo"] for sv in resumen["servicios"]} == {"RESINA-SIMPLE", "PROFILAXIS"}


def test_consulta_repregunta_si_no_reconoce_insumos(catalogo):
    s = Sesion()
    hablar(s, "resumen de consulta", catalogo)
    hablar(s, "María Quispe", catalogo)
    hablar(s, "una limpieza", catalogo)
    paso_antes = s.paso
    out = hablar(s, "no me acuerdo bien", catalogo)
    assert s.paso == paso_antes, "no debe avanzar si no reconoció nada"
    assert "catálogo" in out[0].texto.lower() or "catalogo" in out[0].texto.lower()


def test_consulta_repregunta_si_falta_el_monto(catalogo):
    s = Sesion()
    hablar(s, "consulta", catalogo)
    hablar(s, "Luis Torres", catalogo)
    hablar(s, "una extracción", catalogo)
    hablar(s, "dos anestesias", catalogo)
    paso_antes = s.paso
    hablar(s, "pagó con tarjeta", catalogo)
    assert s.paso == paso_antes, "sin monto no avanza"


def test_pago_mixto_se_conserva_completo(catalogo):
    s = Sesion()
    hablar(s, "consulta", catalogo)
    hablar(s, "Elena Vargas", catalogo)
    hablar(s, "un implante", catalogo)
    hablar(s, "dos anestesias", catalogo)
    hablar(s, "dos mil quinientos soles, mil en efectivo y mil quinientos por transferencia",
           catalogo)
    out = hablar(s, "ninguna", catalogo)
    resumen = out[-1].adjunto
    assert resumen["total_bruto"] == 2500
    assert set(resumen["metodos_pago"]) == {"efectivo", "transferencia"}


# ------------------------------------------------------------- inventario

def test_inventario_acumula_entre_audios(catalogo):
    s = Sesion()
    hablar(s, "inventario", catalogo)
    hablar(s, "doce pastas y tres cepillos", catalogo, audio=True)
    hablar(s, "cinco enjuagues", catalogo, audio=True)
    assert s.conteo == {"PASTA-DENTAL": 12, "CEPILLO": 3, "ENJUAGUE": 5}


def test_inventario_lo_ultimo_dicho_manda(catalogo):
    """El médico se corrige en un audio posterior."""
    s = Sesion()
    hablar(s, "inventario", catalogo)
    hablar(s, "tres cepillos", catalogo, audio=True)
    hablar(s, "perdón, eran nueve cepillos", catalogo, audio=True)
    assert s.conteo["CEPILLO"] == 9


def test_inventario_reporta_faltantes_al_cerrar(catalogo):
    s = Sesion()
    hablar(s, "inventario", catalogo)
    hablar(s, "doce pastas", catalogo, audio=True)
    out = hablar(s, "listo", catalogo)
    texto = out[0].texto
    assert "faltaron" in texto.lower()
    assert not s.terminado, "no se cierra con faltantes: se le ofrece completarlos"
    resumen = out[0].adjunto
    assert resumen["contados"] == 1
    assert resumen["total"] == len(catalogo.de_familia("insumo"))


def test_inventario_igual_que_la_ultima_vez(catalogo):
    previo = {e.codigo: 7 for e in catalogo.de_familia("insumo")}
    s = Sesion()
    hablar(s, "inventario", catalogo)
    hablar(s, "doce pastas", catalogo, previo=previo, audio=True)
    hablar(s, "listo", catalogo, previo=previo)
    out = hablar(s, "igual", catalogo, previo=previo)
    assert s.terminado
    assert s.conteo["PASTA-DENTAL"] == 12, "lo dictado no se pisa"
    assert s.conteo["CEPILLO"] == 7, "lo que faltaba toma el valor anterior"
    filas = {f["codigo"]: f for f in out[0].adjunto["filas"]}
    assert filas["PASTA-DENTAL"]["diferencia"] == 5


def test_inventario_avisa_producto_sin_cantidad(catalogo):
    s = Sesion()
    hablar(s, "inventario", catalogo)
    out = hablar(s, "se acabaron los cepillos", catalogo, audio=True)
    assert "cantidad" in out[0].texto.lower()
    assert "CEPILLO" not in s.conteo


def test_inventario_completo_cierra_solo(catalogo):
    s = Sesion()
    hablar(s, "inventario", catalogo)
    dictado = " y ".join(f"cinco {e.nombre.lower()}" for e in catalogo.de_familia("insumo"))
    hablar(s, dictado, catalogo, audio=True)
    out = hablar(s, "listo", catalogo)
    assert s.terminado
    assert "actualizados" in out[0].texto.lower()


# ------------------------------------------------------------ menú numerado

@pytest.mark.parametrize("respuesta,esperado", [
    ("1", "consulta"), ("2", "inventario"),
    ("opción 2", "inventario"), ("la 1", "consulta"),
    ("uno", "consulta"), ("dos", "inventario"),
])
def test_menu_acepta_numero(catalogo, respuesta, esperado):
    s = Sesion()
    hablar(s, "hola", catalogo)
    hablar(s, respuesta, catalogo)
    assert s.flujo == esperado


def test_el_menu_muestra_los_numeros(catalogo):
    s = Sesion()
    out = hablar(s, "hola", catalogo)
    assert "1 ·" in out[0].texto and "2 ·" in out[0].texto
