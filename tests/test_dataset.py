"""Testes do domínio: dados da escala, busca, ranking e próximas tarefas."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

import app

BRT = timezone(timedelta(hours=-3))


# ---------------------------------------------------------------------------
# Snapshot embutido
# ---------------------------------------------------------------------------


def test_snapshot_tem_a_escala_completa(dataset):
    assert len(dataset["monitores"]) == 52
    assert len(dataset["atividades"]) == 26
    assert len(dataset["cronograma"]) == 13


def test_snapshot_json_e_valido_e_sem_lixo():
    payload = json.loads(app.DATASET_JSON)
    assert set(payload) == {"monitores", "atividades", "cronograma"}
    assert all(m["nome"].strip() for m in payload["monitores"])


def test_todo_monitor_tem_horas_e_funcoes(monitores):
    for monitor in monitores:
        assert monitor["horas"] >= 0
        assert monitor["funcoes"] >= 1
        assert monitor["lista"]
        assert monitor["nome"] == monitor["nome"].strip()


def test_nomes_sao_unicos(monitores):
    nomes = [m["nome"].lower() for m in monitores]
    assert len(nomes) == len(set(nomes))


def test_total_de_horas_confere(monitores):
    assert app.total_hours(monitores) == pytest.approx(891.0, abs=0.1)


def test_ordenacao_alfabetica_ignora_acento(monitores):
    nomes = [app.strip_accents(m["nome"]).lower() for m in monitores]
    assert nomes == sorted(nomes)


# ---------------------------------------------------------------------------
# Normalização defensiva
# ---------------------------------------------------------------------------


def test_normalize_descarta_registros_invalidos():
    sujo = {
        "monitores": [
            {"nome": "  Ana  ", "horas": "12,5", "funcoes": "3.6", "lista": None},
            {"nome": "", "horas": 1},
            {"nome": "ana", "horas": 99},
            "não é dicionário",
            {"nome": "Bia", "horas": "abc", "dias": [{"dia": "Dia 1", "itens": [{"atividade": ""}]}]},
        ],
        "atividades": [{"atividade": ""}, {"atividade": "Apoio", "vagas": "2"}],
        "cronograma": [{"atividade": "Café"}, {"atividade": ""}],
    }
    limpo = app.normalize_dataset(sujo)
    assert [m["nome"] for m in limpo["monitores"]] == ["Ana", "Bia"]
    assert limpo["monitores"][0]["horas"] == 12.5
    assert limpo["monitores"][0]["funcoes"] == 4
    assert limpo["monitores"][1]["horas"] == 0.0
    assert limpo["monitores"][1]["dias"][0]["itens"] == []
    assert len(limpo["atividades"]) == 1
    assert limpo["atividades"][0]["vagas"] == 2
    assert len(limpo["cronograma"]) == 1


def test_normalize_aceita_none_e_lixo():
    assert app.normalize_dataset(None) == {
        "monitores": [],
        "atividades": [],
        "cronograma": [],
    }
    assert app.normalize_dataset({"monitores": "nada"})["monitores"] == []


# ---------------------------------------------------------------------------
# Busca
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "busca, esperado",
    [
        ("leticia", "Letícia Moura Lemos"),
        ("LETÍCIA", "Letícia Moura Lemos"),
        ("rebecca", "Rebecca da Silva Souza"),
        ("  samuel ", "Samuel Victor Alventino Silva"),
    ],
)
def test_busca_ignora_acento_e_caixa(monitores, busca, esperado):
    achados = app.search_people(monitores, busca)
    assert esperado in [m["nome"] for m in achados]


def test_busca_vazia_devolve_todos(monitores):
    assert len(app.search_people(monitores, "")) == len(monitores)
    assert len(app.search_people(monitores, "   ")) == len(monitores)


def test_busca_sem_resultado(monitores):
    assert app.search_people(monitores, "zzzz-nao-existe") == []


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------


def test_ranking_ordenado_por_horas(monitores):
    ranking = app.rank_people(monitores)
    horas = [m["horas"] for m in ranking]
    assert horas == sorted(horas, reverse=True)
    assert ranking[0]["nome"] == "Rebecca da Silva Souza"
    assert ranking[0]["horas"] == 33.5


def test_ranking_e_estavel_com_entrada_embaralhada(monitores):
    import random

    bagunçado = list(monitores)
    random.Random(42).shuffle(bagunçado)
    assert [m["nome"] for m in app.rank_people(bagunçado)] == [
        m["nome"] for m in app.rank_people(monitores)
    ]


def test_ranking_top_n(monitores):
    assert len(app.rank_people(monitores, top=3)) == 3
    assert app.rank_people(monitores, top=0) == app.rank_people(monitores)


def test_ranking_desempata_por_funcoes():
    empatados = [
        {"nome": "B", "horas": 10, "funcoes": 2},
        {"nome": "A", "horas": 10, "funcoes": 3},
        {"nome": "C", "horas": 10, "funcoes": 2},
    ]
    assert [m["nome"] for m in app.rank_people(empatados)] == ["A", "B", "C"]


# ---------------------------------------------------------------------------
# Horários
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "entrada, esperado",
    [
        ("07:00", 420),
        ("7h30", 450),
        (" 23:59 ", 1439),
        ("00:00", 0),
        ("24:00", None),
        ("07:60", None),
        ("", None),
        (None, None),
        ("qualquer coisa", None),
    ],
)
def test_parse_hhmm(entrada, esperado):
    assert app.parse_hhmm(entrada) == esperado


def test_format_minutes():
    assert app.format_minutes(0) == "00:00"
    assert app.format_minutes(450) == "07:30"
    assert app.format_minutes(-10) == "00:00"


def test_assignment_datetime():
    assert app.assignment_datetime(0, "07:00") == datetime(2026, 11, 5, 7, 0, tzinfo=BRT)
    assert app.assignment_datetime(2, "23:30") == datetime(2026, 11, 7, 23, 30, tzinfo=BRT)
    assert app.assignment_datetime(9, "07:00") is None
    assert app.assignment_datetime(0, "xx") is None


def test_assignments_ordenados_e_com_madrugada(monitores):
    rebecca = next(m for m in monitores if m["nome"] == "Rebecca da Silva Souza")
    assignments = app.monitor_assignments(rebecca)
    inicios = [a["inicio"] for a in assignments]
    assert inicios == sorted(inicios)
    assert len(assignments) == sum(len(d["itens"]) for d in rebecca["dias"])


def test_tarefa_que_vira_a_madrugada():
    monitor = {
        "nome": "Teste",
        "dias": [
            {"dia": "Dia 7 (sáb)", "itens": [{"ini": "23:30", "fim": "01:00", "atividade": "Ônibus"}]}
        ],
    }
    assignment = app.monitor_assignments(monitor)[0]
    assert assignment["fim_dt"] - assignment["inicio"] == timedelta(hours=1, minutes=30)


def test_proxima_tarefa_antes_durante_e_depois(monitores):
    rebecca = next(m for m in monitores if m["nome"] == "Rebecca da Silva Souza")
    antes = app.next_assignment(rebecca, datetime(2026, 11, 4, 12, 0, tzinfo=BRT))
    assert antes is not None and antes["ini"] == "07:00"

    durante = app.next_assignment(rebecca, datetime(2026, 11, 5, 13, 0, tzinfo=BRT))
    assert durante is not None and durante["atividade"].startswith("Credenciamento (tarde)")

    depois = app.next_assignment(rebecca, datetime(2026, 11, 8, 12, 0, tzinfo=BRT))
    assert depois is None


def test_proxima_tarefa_sem_fuso_nao_quebra(monitores):
    rebecca = next(m for m in monitores if m["nome"] == "Rebecca da Silva Souza")
    assert app.next_assignment(rebecca, datetime(2026, 11, 5, 8, 0)) is not None


def test_horas_por_dia(monitores):
    rebecca = next(m for m in monitores if m["nome"] == "Rebecca da Silva Souza")
    por_dia = dict(app.hours_by_day(rebecca))
    assert por_dia["Dia 5 (qui)"] == pytest.approx(14.5)
    assert all(valor >= 0 for valor in por_dia.values())


def test_chaves_de_tarefa_sao_unicas_e_estaveis(monitores):
    for monitor in monitores:
        chaves = app.monitor_task_keys(monitor)
        assert len(chaves) == len(set(chaves))


# ---------------------------------------------------------------------------
# CSV ao vivo (Google Sheets)
# ---------------------------------------------------------------------------

CSV_EXEMPLO = """Nome,ID atividade,Data,Início,Fim,Atividade,Local,Horas
Ana Silva,D5-01,05/11/2026,07:00,12:00,Credenciamento (manhã),Sala 05,"5,0"
Bia Souza,D5-01,05/11/2026,07:00,12:00,Credenciamento (manhã),Sala 05,"5,0"
Ana Silva,D5-02,05/11/2026,12:00,18:00,Credenciamento (tarde),Sala 05,"6,0"
Bia Souza,D6-01,06/11/2026,08:00,10:00,Café da manhã,Restaurante,"2,0"
"""


def test_csv_gera_monitores_e_atividades():
    data = app.dataset_from_allocations_csv(CSV_EXEMPLO)
    assert [m["nome"] for m in data["monitores"]] == ["Ana Silva", "Bia Souza"]
    ana = data["monitores"][0]
    assert ana["horas"] == pytest.approx(11.0)
    assert ana["funcoes"] == 2
    assert len(data["atividades"]) == 3
    credenciamento = data["atividades"][0]
    assert sorted(credenciamento["monitores"]) == ["Ana Silva", "Bia Souza"]
    assert credenciamento["escalados"] == 2
    assert credenciamento["vagas"] == 2


def test_csv_vazio_ou_invalido_devolve_vazio():
    for entrada in ("", "   ", "coluna1,coluna2\n1,2\n"):
        assert app.dataset_from_allocations_csv(entrada)["monitores"] == []


def test_build_dataset_usa_csv_quando_valido():
    data = app.build_dataset(csv_text=CSV_EXEMPLO)
    assert len(data["monitores"]) == 2


def test_build_dataset_cai_no_snapshot_com_csv_ruim():
    data = app.build_dataset(csv_text="lixo,lixo\n1,2")
    assert len(data["monitores"]) == 52


def test_build_dataset_json_ruim_nao_quebra():
    data = app.build_dataset(payload="{isso não é json")
    assert data == {"monitores": [], "atividades": [], "cronograma": []}


def test_fetch_csv_sem_url_nao_faz_nada():
    assert app.fetch_csv("") == ""


def test_weekday_pt_aceita_formatos():
    assert app._weekday_pt("05/11/2026") == "Quinta-feira"
    assert app._weekday_pt("2026-11-07") == "Sábado"
    assert app._weekday_pt("46331") == "Quinta-feira"
    assert app._weekday_pt("") == ""


def test_itens_do_dia_ficam_em_ordem_de_horario():
    csv_fora_de_ordem = (
        "Nome,ID atividade,Data,Início,Fim,Atividade,Local,Horas\n"
        "Ana Silva,D5-02,05/11/2026,18:00,22:00,Jantar,Sala,4\n"
        "Ana Silva,D5-01,05/11/2026,07:00,12:00,Credenciamento,Sala,5\n"
    )
    data = app.dataset_from_allocations_csv(csv_fora_de_ordem)
    itens = data["monitores"][0]["dias"][0]["itens"]
    assert [item["ini"] for item in itens] == ["07:00", "18:00"]


def test_ordem_dos_dias_da_semana():
    assert app.day_order("Dia 5 (qui)") == 5
    assert app.day_order("Quinta-feira") == 3
    assert app.day_order("Sábado") == 5
    assert app.day_order("Domingo") == 6
    assert app.day_order("") == 99
    rotulos = ["Dia 7 (sáb)", "Dia 5 (qui)", "Dia 6 (sex)"]
    assert sorted(rotulos, key=app.day_order) == ["Dia 5 (qui)", "Dia 6 (sex)", "Dia 7 (sáb)"]


def test_csv_ao_vivo_herda_lista_e_reuniao_do_snapshot():
    csv_real = (
        "Nome,ID atividade,Data,Início,Fim,Atividade,Local,Horas\n"
        "Rebecca da Silva Souza,D5-01,05/11/2026,07:00,12:00,Credenciamento,Sala,5\n"
        "Pessoa Nova,D5-01,05/11/2026,07:00,12:00,Credenciamento,Sala,5\n"
    )
    data = app.build_dataset(csv_text=csv_real)
    por_nome = {m["nome"]: m for m in data["monitores"]}
    assert por_nome["Rebecca da Silva Souza"]["lista"] == "Núcleo (Estatísticas)"
    assert por_nome["Rebecca da Silva Souza"]["reuniao"] is True
    assert por_nome["Pessoa Nova"]["lista"] == "Escala"
    assert por_nome["Pessoa Nova"]["reuniao"] is False
