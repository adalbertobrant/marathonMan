"""Programação oficial: dados, janelas de horário e a tela em si."""

from __future__ import annotations

from datetime import date, datetime

import pytest
from conftest import botao, navegar

import app

# ---------------------------------------------------------------------------
# Dados
# ---------------------------------------------------------------------------


def test_quatro_dias_na_ordem():
    assert [dia.data for dia in app.PROGRAMACAO] == [
        date(2026, 11, 5),
        date(2026, 11, 6),
        date(2026, 11, 7),
        date(2026, 11, 8),
    ]
    assert [dia.dia for dia in app.PROGRAMACAO] == [
        "Quinta-feira",
        "Sexta-feira",
        "Sábado",
        "Domingo",
    ]


def test_cada_dia_tem_titulo_e_itens():
    for dia in app.PROGRAMACAO:
        assert dia.titulo
        assert dia.itens, f"{dia.dia} está sem itens"


def test_todo_item_tem_hora_titulo_tipo_e_local():
    for dia in app.PROGRAMACAO:
        for item in dia.itens:
            assert item.hora.strip()
            assert item.titulo.strip()
            assert item.tipo.strip()
            assert item.local.strip()


def test_total_de_momentos_e_o_esperado():
    assert sum(len(dia.itens) for dia in app.PROGRAMACAO) == 34


def test_grande_final_esta_no_sabado():
    sabado = app.programacao_do_dia(date(2026, 11, 7))
    assert sabado is not None
    titulos = [item.titulo for item in sabado.itens]
    assert "Final da Maratona SBC de Programação 2026" in titulos
    assert any(item.tipo == "Premiação Oficial" for item in sabado.itens)


def test_programacao_do_dia_inexistente():
    assert app.programacao_do_dia(date(2026, 11, 9)) is None


# ---------------------------------------------------------------------------
# Janelas de horário
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("09:00 – 12:00", (540, 720)),
        ("07:00 - 08:30", (420, 510)),
        ("15:30", (930, 990)),
        ("Até as 12:00", (720, 780)),
        ("23:30 – 01:00", (1410, 1500)),
        ("  19:00 – 19:30  ", (1140, 1170)),
    ],
)
def test_intervalos(texto, esperado):
    assert app._prog_intervalo(texto) == esperado


@pytest.mark.parametrize("texto", ["", "a definir", "em breve"])
def test_intervalos_sem_horario(texto):
    assert app._prog_intervalo(texto) is None


def test_item_acontecendo_no_meio_do_bloco():
    sexta = app.programacao_do_dia(date(2026, 11, 6))
    indice = app.item_acontecendo(sexta, datetime(2026, 11, 6, 14, 30))
    assert indice is not None
    assert sexta.itens[indice].titulo == "Sessão aberta de treino - Aquecimento (Warm-up)"


def test_item_acontecendo_antes_de_tudo():
    sexta = app.programacao_do_dia(date(2026, 11, 6))
    assert app.item_acontecendo(sexta, datetime(2026, 11, 6, 5, 0)) is None


def test_item_acontecendo_depois_de_tudo():
    domingo = app.programacao_do_dia(date(2026, 11, 8))
    assert app.item_acontecendo(domingo, datetime(2026, 11, 8, 23, 0)) is None


def test_item_acontecendo_so_vale_no_proprio_dia():
    sabado = app.programacao_do_dia(date(2026, 11, 7))
    assert app.item_acontecendo(sabado, datetime(2026, 11, 6, 15, 0)) is None


def test_virada_de_meia_noite_ainda_esta_no_intervalo():
    sabado = app.programacao_do_dia(date(2026, 11, 7))
    indice = app.item_acontecendo(sabado, datetime(2026, 11, 7, 23, 45))
    assert indice is not None
    assert sabado.itens[indice].hora == "23:30 – 01:00"


# ---------------------------------------------------------------------------
# Tela
# ---------------------------------------------------------------------------


def test_pagina_programacao_mostra_os_quatro_dias(app_factory):
    at = app_factory()
    at.run()
    botao(at, "✅ Pode registrar").click()
    at.run()
    navegar(at, "programacao")

    assert list(at.exception) == []
    opcoes = at.radio(key="prog_dia").options
    assert opcoes == [
        "05/11 · Quinta-feira",
        "06/11 · Sexta-feira",
        "07/11 · Sábado",
        "08/11 · Domingo",
    ]

    # O dia aberto por padrão depende da data de hoje, então escolhemos um.
    at.radio(key="prog_dia").set_value("05/11 · Quinta-feira")
    at.run()

    texto = " ".join(m.value for m in at.markdown)
    assert "Recepção, Credenciamento e Abertura Social" in texto
    assert "Reunião do Comitê Diretor" in texto
    assert "ajustes" in texto


def test_pagina_programacao_troca_de_dia(app_factory):
    at = app_factory()
    at.run()
    navegar(at, "programacao")
    at.radio(key="prog_dia").set_value("07/11 · Sábado")
    at.run()

    texto = " ".join(m.value for m in at.markdown)
    assert "A Grande Final Brasileira e Cerimônia de Premiação" in texto
    assert "Final da Maratona SBC de Programação 2026" in texto
    assert "23:30 – 01:00" in texto


def test_home_leva_para_a_programacao(app_factory):
    at = app_factory()
    at.run()
    botao(at, "📅 Programação oficial · 05 a 08/11 · Uberlândia-MG").click()
    at.run()

    assert at.session_state["nav"] == "programacao"
    assert "programacao" in at.session_state["views"]
