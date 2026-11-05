"""Testes do funil: caminho correto, abandono e tempo por tela."""

from __future__ import annotations

import app

CANON = list(app.CANONICAL_STEPS)


def test_caminho_completo_e_considerado_correto():
    resultado = app.analyze_path(CANON)
    assert resultado["status"] == "completo"
    assert resultado["completude"] == 1.0
    assert resultado["faltando"] == []
    assert resultado["fora_de_ordem"] is False
    assert resultado["primeira_falha"] is None
    assert resultado["parou_em"] == CANON[-1]


def test_caminho_pela_metade_e_parcial():
    resultado = app.analyze_path(CANON[:3])
    assert resultado["status"] == "parcial"
    assert resultado["completude"] == round(3 / 7, 3)
    assert resultado["faltando"] == CANON[3:]
    assert resultado["parou_em"] == CANON[2]
    assert resultado["primeira_falha"] is None


def test_pular_uma_tela_aponta_a_primeira_falha():
    caminho = ["inicio", "resumo", "tarefas"]
    resultado = app.analyze_path(caminho)
    assert resultado["primeira_falha"] == "quem"
    assert "quem" in resultado["faltando"]


def test_voltar_atras_marca_fora_de_ordem():
    caminho = ["inicio", "quem", "resumo", "quem"]
    resultado = app.analyze_path(caminho)
    assert resultado["fora_de_ordem"] is True
    assert resultado["sequencia"] == caminho


def test_repeticao_seguida_e_compactada():
    caminho = ["inicio", "inicio", "inicio", "quem", "quem"]
    assert app.analyze_path(caminho)["sequencia"] == ["inicio", "quem"]


def test_telas_desconhecidas_sao_ignoradas():
    resultado = app.analyze_path(["inicio", "hacker", "quem", "admin"])
    assert resultado["sequencia"] == ["inicio", "quem"]


def test_caminho_vazio():
    resultado = app.analyze_path([])
    assert resultado["status"] == "incompleto"
    assert resultado["completude"] == 0.0
    assert resultado["parou_em"] == ""
    assert resultado["faltando"] == CANON


def test_caminho_so_com_lixo():
    resultado = app.analyze_path(["x", "y"])
    assert resultado["sequencia"] == []
    assert resultado["status"] == "incompleto"


def test_completude_nao_passa_de_um():
    assert app.analyze_path(CANON * 3)["completude"] == 1.0


def test_rotulos_do_caminho():
    assert app.path_label(["inicio", "quem"]) == "Início → Quem é você?"
    assert app.path_badges(["inicio", "quem"]) == "🍉 → 🙋"
    assert app.path_label([]) == "—"
    assert app.path_badges([]) == "—"
    assert app.path_badges(["desconhecida"]) == "❓"


def _sessao(sequencia, pessoa="", status=None):
    analise = app.analyze_path(sequencia)
    return {
        "sid": "s",
        "sequencia": analise["sequencia"],
        "completude": analise["completude"],
        "status": status or analise["status"],
        "fora_de_ordem": analise["fora_de_ordem"],
        "primeira_falha": analise["primeira_falha"],
        "parou_em": analise["parou_em"],
        "pessoa": pessoa,
        "pais": "BR",
        "primeiro": "2026-11-04T10:00:00+00:00",
        "ultimo": "2026-11-04T10:05:00+00:00",
        "eventos": len(sequencia),
    }


def test_relatorio_do_funil():
    sessoes = [
        _sessao(CANON, pessoa="Ana"),
        _sessao(CANON[:2]),
        _sessao(["inicio", "quem", "resumo", "quem"]),
        _sessao([]),
    ]
    relatorio = app.funnel_report(sessoes)
    assert relatorio["sessoes"] == 4
    assert relatorio["completas"] == 1
    assert relatorio["parciais"] == 2
    assert relatorio["identificadas"] == 1
    assert relatorio["taxa_conclusao"] == 0.25
    assert relatorio["fora_de_ordem"] == 1
    assert relatorio["por_tela"]["inicio"] == 3
    assert relatorio["abandono"]["quem"] == 2


def test_relatorio_do_funil_sem_sessoes():
    relatorio = app.funnel_report([])
    assert relatorio["sessoes"] == 0
    assert relatorio["taxa_conclusao"] == 0.0
    assert relatorio["por_tela"] == {}


def test_tempo_por_tela_calcula_media():
    eventos = [
        {"sid": "a", "kind": "view", "screen": "inicio", "ts": "2026-11-04T10:00:00+00:00"},
        {"sid": "a", "kind": "leave", "screen": "inicio", "ts": "2026-11-04T10:00:30+00:00"},
        {"sid": "b", "kind": "view", "screen": "inicio", "ts": "2026-11-04T11:00:00+00:00"},
        {"sid": "b", "kind": "leave", "screen": "inicio", "ts": "2026-11-04T11:01:30+00:00"},
    ]
    assert app.dwell_by_screen(eventos) == {"inicio": 60.0}


def test_tempo_por_tela_ignora_aba_esquecida():
    eventos = [
        {"sid": "a", "kind": "view", "screen": "inicio", "ts": "2026-11-04T10:00:00+00:00"},
        {"sid": "a", "kind": "leave", "screen": "inicio", "ts": "2026-11-04T13:00:00+00:00"},
    ]
    assert app.dwell_by_screen(eventos) == {}


def test_tempo_por_tela_ignora_saida_orfa():
    eventos = [
        {"sid": "a", "kind": "leave", "screen": "inicio", "ts": "2026-11-04T10:00:00+00:00"},
    ]
    assert app.dwell_by_screen(eventos) == {}


def test_tempo_por_tela_com_timestamp_quebrado():
    eventos = [
        {"sid": "a", "kind": "view", "screen": "inicio", "ts": "ontem"},
        {"sid": "a", "kind": "leave", "screen": "inicio", "ts": "hoje"},
    ]
    assert app.dwell_by_screen(eventos) == {}
