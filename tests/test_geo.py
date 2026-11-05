"""Testes de geolocalização, bloqueio de VPN e decisão de acesso.

Nenhum teste aqui usa rede: os lookups são funções falsas.
"""

from __future__ import annotations

import pytest

import app


def settings(**kwargs) -> app.Settings:
    base = {"db_path": ":memory:"}
    base.update(kwargs)
    return app.Settings(**base)


# ---------------------------------------------------------------------------
# Cabeçalhos e IP
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "headers, esperado",
    [
        ({"cf-ipcountry": "BR"}, "BR"),
        ({"CF-IPCountry": "br"}, "BR"),
        ({"X-Vercel-IP-Country": "PT"}, "PT"),
        ({"x-country-code": "US"}, "US"),
        ({"cf-ipcountry": "T1"}, "T1"),
        ({"cf-ipcountry": "XX"}, "??"),
        ({"cf-ipcountry": "Brasil"}, "??"),
        ({}, "??"),
        (None, "??"),
    ],
)
def test_detect_country_por_cabecalho(headers, esperado):
    pais, origem = app.detect_country(headers)
    assert pais == esperado
    if esperado == "??":
        assert origem in {"desconhecido", "header:cf-ipcountry"}
    else:
        assert origem.startswith("header:")


def test_header_value_ignora_caixa():
    assert app.header_value({"X-Real-IP": "1.2.3.4"}, "x-real-ip") == "1.2.3.4"
    assert app.header_value({}, "x-real-ip") == ""
    assert app.header_value(None, "x-real-ip") == ""


def test_client_ip_pega_o_primeiro_da_cadeia():
    headers = {"x-forwarded-for": "189.1.2.3, 10.0.0.1, 10.0.0.2"}
    assert app.client_ip(headers) == "189.1.2.3"


def test_client_ip_prioriza_cabecalhos_de_cdn():
    headers = {
        "cf-connecting-ip": "189.9.9.9",
        "x-forwarded-for": "10.0.0.1",
    }
    assert app.client_ip(headers) == "189.9.9.9"


@pytest.mark.parametrize(
    "ip, publico",
    [
        ("189.1.2.3", True),
        ("8.8.8.8", True),
        ("10.0.0.1", False),
        ("192.168.0.1", False),
        ("127.0.0.1", False),
        ("169.254.1.1", False),
        ("::1", False),
        ("2001:4860:4860::8888", True),
        ("não-é-ip", False),
        ("", False),
    ],
)
def test_is_public_ip(ip, publico):
    assert app.is_public_ip(ip) is publico


def test_lookup_so_acontece_para_ip_publico():
    chamadas = []

    def lookup(ip):
        chamadas.append(ip)
        return "BR"

    pais, origem = app.detect_country({}, ip="10.0.0.1", lookup=lookup)
    assert (pais, origem) == ("LOCAL", "ip-privado")
    assert chamadas == []

    pais, origem = app.detect_country({}, ip="189.1.2.3", lookup=lookup)
    assert (pais, origem) == ("BR", "lookup")
    assert chamadas == ["189.1.2.3"]


def test_lookup_que_explode_nao_derruba():
    def lookup(ip):
        raise RuntimeError("fora do ar")

    pais, origem = app.detect_country({}, ip="189.1.2.3", lookup=lookup)
    assert pais == "??"


def test_lookup_com_resposta_estranha():
    assert app.detect_country({}, ip="189.1.2.3", lookup=lambda ip: "<html>")[0] == "??"


# ---------------------------------------------------------------------------
# Decisão
# ---------------------------------------------------------------------------


def test_pais_permitido_libera():
    liberado, motivo = app.geo_decision("BR", settings())
    assert liberado is True
    assert "BR" in motivo


def test_pais_estrangeiro_bloqueia():
    liberado, motivo = app.geo_decision("US", settings())
    assert liberado is False
    assert "fora da lista" in motivo


def test_tor_e_bloqueado():
    assert app.geo_decision("T1", settings())[0] is False


def test_desconhecido_tolerante_libera():
    assert app.geo_decision("??", settings())[0] is True
    assert app.geo_decision("LOCAL", settings())[0] is True


def test_desconhecido_estrito_bloqueia():
    cfg = settings(unknown_country_policy="block")
    assert app.geo_decision("??", cfg)[0] is False


def test_geo_desligado_libera_qualquer_pais():
    cfg = settings(geo_mode="off")
    assert app.geo_decision("US", cfg) == (True, "geo desligado")


def test_lista_de_paises_configuravel():
    cfg = settings(allowed_countries=("BR", "PT"))
    assert app.geo_decision("PT", cfg)[0] is True
    assert app.geo_decision("AR", cfg)[0] is False


def test_settings_from_env_le_as_variaveis():
    cfg = app.Settings.from_env(
        {
            "ALLOWED_COUNTRIES": "br, pt",
            "GEO_MODE": "off",
            "UNKNOWN_COUNTRY_POLICY": "block",
            "CONSENT_REQUIRED": "0",
            "ADMIN_PASSWORD": "segredo",
            "RETENTION_DAYS": "15",
            "COOKIE_DAYS": "7",
            "MAX_PHOTO_MB": "3",
            "ENABLE_IP_INTEL": "sim",
            "MARATONA_DB": "/tmp/x.db",
        }
    )
    assert cfg.allowed_countries == ("BR", "PT")
    assert cfg.geo_mode == "off"
    assert cfg.unknown_country_policy == "block"
    assert cfg.consent_required is False
    assert cfg.admin_password == "segredo"
    assert cfg.retention_days == 15
    assert cfg.cookie_days == 7
    assert cfg.max_photo_mb == 3
    assert cfg.ip_intel is True
    assert cfg.db_path == "/tmp/x.db"


def test_settings_from_env_tolera_valores_absurdos():
    cfg = app.Settings.from_env({"GEO_MODE": "banana", "RETENTION_DAYS": "abc"})
    assert cfg.geo_mode == "block"
    assert cfg.retention_days == 90


def test_settings_from_env_vazio_usa_padroes():
    cfg = app.Settings.from_env({})
    assert cfg.allowed_countries == ("BR",)
    assert cfg.geo_mode == "block"
    assert cfg.consent_required is True
    assert cfg.pixel_url == ""


# ---------------------------------------------------------------------------
# Decisão completa (país + reputação de IP)
# ---------------------------------------------------------------------------


def test_assess_access_libera_brasil():
    resultado = app.assess_access({"cf-ipcountry": "BR"}, settings())
    assert resultado["liberado"] is True
    assert resultado["pais"] == "BR"
    assert resultado["ip_presente"] is False


def test_assess_access_bloqueia_estrangeiro():
    resultado = app.assess_access({"cf-ipcountry": "US"}, settings())
    assert resultado["liberado"] is False
    assert "fora da lista" in resultado["motivo"]


def test_assess_access_intel_detecta_proxy():
    def intel(ip, url):
        return {"status": "success", "countryCode": "BR", "proxy": True, "hosting": False}

    resultado = app.assess_access(
        {"cf-ipcountry": "BR", "cf-connecting-ip": "189.1.2.3"},
        settings(ip_intel=True),
        intel=intel,
    )
    assert resultado["liberado"] is False
    assert "VPN" in resultado["motivo"]


def test_assess_access_intel_detecta_datacenter():
    resultado = app.assess_access(
        {"cf-ipcountry": "BR", "cf-connecting-ip": "189.1.2.3"},
        settings(ip_intel=True),
        intel=lambda ip, url: {"status": "success", "hosting": True},
    )
    assert resultado["liberado"] is False


def test_assess_access_intel_completa_pais_desconhecido():
    resultado = app.assess_access(
        {"cf-connecting-ip": "189.1.2.3"},
        settings(ip_intel=True),
        intel=lambda ip, url: {"status": "success", "countryCode": "US"},
    )
    assert resultado["pais"] == "US"
    assert resultado["liberado"] is False
    assert resultado["origem_pais"] == "ip-intel"


def test_assess_access_intel_fora_do_ar_e_tolerado():
    resultado = app.assess_access(
        {"cf-ipcountry": "BR", "cf-connecting-ip": "189.1.2.3"},
        settings(ip_intel=True),
        intel=lambda ip, url: {},
    )
    assert resultado["liberado"] is True


def test_assess_access_intel_desligado_por_padrao():
    chamado = []
    app.assess_access(
        {"cf-ipcountry": "BR", "cf-connecting-ip": "189.1.2.3"},
        settings(),
        intel=lambda ip, url: chamado.append(ip) or {},
    )
    assert chamado == []


def test_ip_intel_sem_ip_ou_url():
    assert app.ip_intel("", "http://x/{ip}") == {}
    assert app.ip_intel("1.2.3.4", "") == {}


def test_ip_intel_com_url_quebrada():
    assert app.ip_intel("1.2.3.4", "http://127.0.0.1:9/{ip}", timeout=0.2) == {}
