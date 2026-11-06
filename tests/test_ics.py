"""Calendário .ics da programação e o recado guardado para 14/11."""

from __future__ import annotations

from datetime import date, datetime, timezone

from conftest import ROOT, navegar

import app


def desdobrar(ics: str) -> str:
    """Desfaz a dobra de linha (RFC 5545) para poder comparar textos."""
    return ics.replace("\r\n ", "")


def eventos(ics: str) -> list[str]:
    return desdobrar(ics).split("BEGIN:VEVENT")[1:]


# ---------------------------------------------------------------------------
# Estrutura do arquivo
# ---------------------------------------------------------------------------


def test_ics_tem_cabecalho_e_rodape():
    ics = app.build_ics()
    assert ics.startswith("BEGIN:VCALENDAR\r\n")
    assert ics.endswith("END:VCALENDAR\r\n")
    assert "VERSION:2.0" in ics
    assert "TZID:America/Sao_Paulo" in ics


def test_ics_tem_os_34_momentos_mais_o_aniversario():
    ics = app.build_ics()
    assert ics.count("BEGIN:VEVENT") == 35
    assert ics.count("END:VEVENT") == 35


def test_todos_os_momentos_aparecem():
    texto = desdobrar(app.build_ics())
    for dia in app.PROGRAMACAO:
        for item in dia.itens:
            assert app._ics_escape(item.titulo) in texto


def test_uids_sao_unicos():
    uids = [
        linha
        for linha in desdobrar(app.build_ics()).splitlines()
        if linha.startswith("UID:")
    ]
    assert len(uids) == 35
    assert len(set(uids)) == 35


def test_nenhuma_linha_passa_de_75_octetos():
    for linha in app.build_ics().split("\r\n"):
        assert len(linha.encode("utf-8")) <= 75


def test_escape_segue_a_rfc_5545():
    assert app._ics_escape("a,b;c\\d\ne") == "a\\,b\\;c\\\\d\\ne"
    assert app._ics_escape("") == ""


# ---------------------------------------------------------------------------
# Horários
# ---------------------------------------------------------------------------


def test_checkout_vira_evento_de_dia_inteiro():
    texto = desdobrar(app.build_ics())
    assert "DTSTART;VALUE=DATE:20261108" in texto
    assert "DTEND;VALUE=DATE:20261109" in texto


def test_virada_de_meia_noite_termina_no_dia_seguinte():
    texto = desdobrar(app.build_ics())
    assert "DTSTART;TZID=America/Sao_Paulo:20261107T233000" in texto
    assert "DTEND;TZID=America/Sao_Paulo:20261108T010000" in texto


def test_primeiro_evento_comeca_as_nove():
    texto = desdobrar(app.build_ics())
    assert "DTSTART;TZID=America/Sao_Paulo:20261105T090000" in texto
    assert "DTEND;TZID=America/Sao_Paulo:20261105T120000" in texto


def test_dtstamp_usa_o_momento_informado():
    ics = app.build_ics(datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc))
    assert "DTSTAMP:20261106T120000Z" in ics


# ---------------------------------------------------------------------------
# O recado de 14/11
# ---------------------------------------------------------------------------


def test_aniversario_no_dia_14_com_alarme():
    aniversario = next(e for e in eventos(app.build_ics()) if "aniversario" in e)
    assert "DTSTART;TZID=America/Sao_Paulo:20261114T090000" in aniversario
    assert "DTEND;TZID=America/Sao_Paulo:20261114T093000" in aniversario
    assert "BEGIN:VALARM" in aniversario
    assert "ACTION:DISPLAY" in aniversario
    assert "TRIGGER:-PT5M" in aniversario
    assert "END:VALARM" in aniversario


def test_recado_completo_dentro_do_aniversario():
    aniversario = next(e for e in eventos(app.build_ics()) if "aniversario" in e)
    assert app._ics_escape(app.RECADO_ANIVERSARIO) in aniversario


def test_constantes_do_recado():
    assert date(2026, 11, 14) == app.ANIVERSARIO
    assert "dev.to/adalbertobrant" in app.RECADO_ANIVERSARIO
    assert "https://github.com/adalbertobrant/marathonMan" in app.RECADO_ANIVERSARIO
    assert "experimento que é viver" in app.RECADO_ANIVERSARIO


def test_arquivo_estatico_esta_sincronizado():
    """`make ics` precisa ser rodado quando a programação mudar."""
    destino = ROOT / "docs" / "programacao-final-sbc-2026.ics"
    assert destino.exists()
    esperado = app.build_ics(datetime(2026, 11, 5, 0, 0, tzinfo=timezone.utc))
    assert destino.read_bytes().decode("utf-8") == esperado


# ---------------------------------------------------------------------------
# Tela
# ---------------------------------------------------------------------------


def test_pagina_oferece_o_download(app_factory):
    at = app_factory()
    at.run()
    navegar(at, "programacao")

    assert list(at.exception) == []
    botoes = [d.label for d in at.download_button]
    assert botoes == ["📅 Adicionar à minha agenda (.ics)"]


def test_pagina_mostra_o_pedido_de_like_e_o_recado(app_factory):
    at = app_factory()
    at.run()
    navegar(at, "programacao")

    texto = " ".join(m.value for m in at.markdown)
    assert "Curtiu? Deixa um like" in texto
    assert "github.com/adalbertobrant" in texto
    assert "dev.to/adalbertobrant" in texto
    assert "Recado guardado para 14/11" in texto
    assert "marathonMan" in texto


def test_home_tambem_lembra_do_like(app_factory):
    at = app_factory()
    at.run()
    texto = " ".join(m.value for m in at.markdown)
    assert "Gostou? Segue o" in texto
    assert "marathonMan" in texto
