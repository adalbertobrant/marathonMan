"""Testes de privacidade: pixel, cookie, limpeza de metadados das fotos."""

from __future__ import annotations

import io

import pytest

import app

SID = "c" * 32


def settings(**kwargs) -> app.Settings:
    base = {"db_path": ":memory:"}
    base.update(kwargs)
    return app.Settings(**base)


# ---------------------------------------------------------------------------
# Pixel 1x1
# ---------------------------------------------------------------------------


def test_sem_url_nao_existe_pixel():
    assert app.pixel_markup(settings(), SID, "inicio") == ""


def test_pixel_tem_um_por_um_e_parametros():
    markup = app.pixel_markup(settings(pixel_url="https://exemplo.com/p.gif"), SID, "resumo")
    assert 'width="1"' in markup
    assert 'height="1"' in markup
    assert f"s={SID}" in markup
    assert "p=resumo" in markup
    assert "e=view" in markup


def test_pixel_usa_interrogacao_ou_e_comercial_corretos():
    com_query = app.pixel_markup(settings(pixel_url="https://x.com/p?x=1"), SID, "inicio")
    assert "p?x=1&amp;e=view" in com_query
    sem_query = app.pixel_markup(settings(pixel_url="https://x.com/p"), SID, "inicio")
    assert "p?e=view" in sem_query


def test_pixel_escapa_a_url():
    markup = app.pixel_markup(
        settings(pixel_url='https://x.com/p"><script>alert(1)</script>'), SID, "inicio"
    )
    assert "<script>" not in markup
    assert "&quot;" in markup or "&lt;" in markup


def test_pixel_e_invisivel_e_sem_texto_alternativo():
    markup = app.pixel_markup(settings(pixel_url="https://x.com/p"), SID, "inicio")
    assert 'alt=""' in markup
    assert "left:-9999px" in markup


def test_render_pixel_sem_url_nao_faz_nada():
    app.render_pixel(settings(), SID, "inicio")  # não deve levantar


def test_render_pixel_com_url_nao_quebra():
    app.render_pixel(settings(pixel_url="https://x.com/p"), SID, "inicio")


# ---------------------------------------------------------------------------
# Cookie
# ---------------------------------------------------------------------------


def test_script_do_cookie_contem_nome_dias_e_id():
    script = (
        app.COOKIE_JS.replace("__COOKIE_NAME__", "melancias_sid")
        .replace("__COOKIE_DAYS__", "30")
        .replace("__SID__", SID)
    )
    assert "melancias_sid" in script
    assert "30" in script
    assert SID in script
    assert "SameSite=Lax" in script


def test_cookie_nao_roda_sem_consentimento_no_fluxo_principal():
    """A função só é chamada com consentimento; aqui garantimos que ela é segura."""
    app.cookie_bridge(settings(), SID)  # não deve levantar


def test_supports_html_js_devolve_booleano():
    assert isinstance(app.supports_html_js(), bool)


def test_run_js_engole_erro():
    app.run_js("console.log('oi')")


def test_sid_novo_tem_32_hex():
    sid = app.new_sid()
    assert len(sid) == 32
    assert app.SID_RE.match(sid)
    assert app.new_sid() != sid


def test_query_param_sid_valida_formato():
    assert app.SID_RE.match("d" * 32)
    assert not app.SID_RE.match("d" * 31)
    assert not app.SID_RE.match("z" * 32)


# ---------------------------------------------------------------------------
# Fotos: metadados fora, tamanho limitado
# ---------------------------------------------------------------------------


def _jpeg_com_exif(largura=400, altura=300) -> bytes:
    from PIL import Image

    imagem = Image.new("RGB", (largura, altura), (255, 77, 109))
    exif = imagem.getexif()
    exif[0x010F] = "CameraSecreta"  # Make
    exif[0x0110] = "ModeloSecreto"  # Model
    buffer = io.BytesIO()
    imagem.save(buffer, format="JPEG", exif=exif)
    return buffer.getvalue()


def test_foto_perde_metadados():
    original = _jpeg_com_exif()
    assert b"CameraSecreta" in original

    limpa, mime = app.sanitize_image(original)
    assert mime == "image/jpeg"
    assert b"CameraSecreta" not in limpa
    assert b"ModeloSecreto" not in limpa

    from PIL import Image

    assert len(Image.open(io.BytesIO(limpa)).getexif()) == 0


def test_foto_grande_e_reduzida():
    from PIL import Image

    grande = _jpeg_com_exif(3000, 2000)
    limpa, _ = app.sanitize_image(grande, max_side=1600)
    largura, altura = Image.open(io.BytesIO(limpa)).size
    assert max(largura, altura) <= 1600
    assert largura > altura  # manteve proporção


def test_png_com_transparencia_continua_png():
    from PIL import Image

    imagem = Image.new("RGBA", (120, 120), (255, 255, 255, 0))
    buffer = io.BytesIO()
    imagem.save(buffer, format="PNG")
    limpa, mime = app.sanitize_image(buffer.getvalue())
    assert mime == "image/png"
    assert Image.open(io.BytesIO(limpa)).mode in {"RGBA", "LA", "P"}


def test_arquivo_invalido_nao_quebra():
    lixo = b"isto nao e uma imagem"
    assert app.sanitize_image(lixo) == (lixo, "original")


def test_foto_nunca_e_gravada_em_disco(tmp_path, monkeypatch):
    """sanitize_image trabalha em memória: o diretório fica intacto."""
    monkeypatch.chdir(tmp_path)
    app.sanitize_image(_jpeg_com_exif())
    assert list(tmp_path.iterdir()) == []


def test_privacidade_do_texto_da_meditacao():
    """Nenhuma função do app grava o texto: só a contagem."""
    from conftest import ROOT

    fonte = (ROOT / "app.py").read_text(encoding="utf-8")
    assert '"total": len(st.session_state.words)' in fonte
    assert 'meta={"texto"' not in fonte
    assert 'meta={"palavra"' not in fonte


def test_politica_aparece_na_pagina_de_privacidade():
    from conftest import ROOT

    fonte = (ROOT / "app.py").read_text(encoding="utf-8")
    assert "Nunca é registrado" in fonte or "NUNCA é registrado" in fonte
    assert "gravação de tela" in fonte


@pytest.mark.parametrize("chave", ["LGPD", "consentimento", "retenção"])
def test_termos_de_transparencia_presentes(chave):
    from conftest import ROOT

    fonte = (ROOT / "app.py").read_text(encoding="utf-8").lower()
    assert chave.lower() in fonte
