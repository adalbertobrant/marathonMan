"""Testes de integração: a aplicação de verdade, tela por tela.

Usa `streamlit.testing.v1.AppTest`, que executa o app.py como o Streamlit faz.
"""

from __future__ import annotations

import pytest
from conftest import botao, navegar

import app

PAGINAS = ["inicio", "quem", "resumo", "tarefas", "destaques", "meditacao", "privacidade"]


def eventos(db_path) -> list[dict]:
    banco = app.AnalyticsStore(db_path)
    linhas = banco.rows()
    banco.close()
    return linhas


def sem_erro(at) -> None:
    assert list(at.exception) == [], list(at.exception)
    assert [e.value for e in at.error] == [], [e.value for e in at.error]


# ---------------------------------------------------------------------------
# Primeiro contato
# ---------------------------------------------------------------------------


def test_primeira_visita_mostra_banner_e_nao_registra(app_factory, tmp_path):
    at = app_factory()
    at.run()
    sem_erro(at)
    texto = " ".join(m.value for m in at.markdown)
    assert "combinado rápido" in texto
    assert eventos(tmp_path / "app.db") == []


def test_dados_da_escala_aparecem_na_home(app_factory):
    at = app_factory()
    at.run()
    metricas = {m.label: m.value for m in at.metric}
    assert metricas["🍉 melancias"] == "52"
    assert metricas["🗓️ atividades"] == "26"


def test_aceitar_consentimento_registra_e_some_o_banner(app_factory, tmp_path):
    at = app_factory()
    at.run()
    botao(at, "✅ Pode registrar").click()
    at.run()
    sem_erro(at)
    assert at.session_state["consent"] == "granted"
    assert "combinado rápido" not in " ".join(m.value for m in at.markdown)

    linhas = eventos(tmp_path / "app.db")
    tipos = {linha["kind"] for linha in linhas}
    assert {"consent", "view"} <= tipos
    assert any(linha["screen"] == "inicio" for linha in linhas)


def test_recusar_consentimento_nao_registra_nada(app_factory, tmp_path):
    at = app_factory()
    at.run()
    botao(at, "🙅 Só o essencial").click()
    at.run()
    sem_erro(at)
    assert at.session_state["consent"] == "denied"
    assert eventos(tmp_path / "app.db") == []
    navegar(at, "resumo")
    sem_erro(at)


# ---------------------------------------------------------------------------
# Navegação
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("pagina", PAGINAS)
def test_toda_pagina_renderiza(app_factory, pagina):
    at = app_factory()
    at.run()
    botao(at, "✅ Pode registrar").click()
    at.run()
    navegar(at, pagina)
    sem_erro(at)


def test_paginas_extras_com_senha(app_factory):
    at = app_factory(ADMIN_PASSWORD="senha-forte")
    at.run()
    navegar(at, "admin")
    sem_erro(at)


def test_stepper_mostra_o_caminho(app_factory):
    at = app_factory()
    at.run()
    botao(at, "✅ Pode registrar").click()
    at.run()
    texto = " ".join(m.value for m in at.markdown)
    assert "mela-stepper" in texto
    assert "Quem é você?" in texto


def test_navegacao_por_botao_da_home(app_factory):
    at = app_factory()
    at.run()
    at.button(key="home_quem").click()
    at.run()
    assert at.session_state["nav"] == "quem"
    sem_erro(at)


# ---------------------------------------------------------------------------
# Fluxo principal: identificar -> resumo -> pronto
# ---------------------------------------------------------------------------


def test_fluxo_identificacao_e_resumo(app_factory, tmp_path):
    at = app_factory()
    at.run()
    botao(at, "✅ Pode registrar").click()
    at.run()
    navegar(at, "quem")

    at.text_input(key="busca_nome").set_value("rebecca")
    at.run()
    at.selectbox(key="select_nome").set_value("Rebecca da Silva Souza")
    at.run()
    botao(at, "✅ Sou eu!").click()
    at.run()

    sem_erro(at)
    assert at.session_state["person"] == "Rebecca da Silva Souza"
    metricas = {m.label: m.value for m in at.metric}
    assert metricas["⏱️ horas"] == "33.5h"
    assert metricas["🧩 funções"] == "8"

    linhas = eventos(tmp_path / "app.db")
    assert any(linha["kind"] == "identify" and linha["person"] == "Rebecca da Silva Souza"
               for linha in linhas)


def test_botao_to_pronto_marca_o_caminho(app_factory, tmp_path):
    at = app_factory()
    at.run()
    botao(at, "✅ Pode registrar").click()
    at.run()
    navegar(at, "quem")
    at.selectbox(key="select_nome").set_value("Rebecca da Silva Souza")
    at.run()
    botao(at, "✅ Sou eu!").click()
    at.run()
    botao(at, "✅ Tô pronto(a) pro dia").click()
    at.run()
    sem_erro(at)
    assert "pronto" in at.session_state["views"]
    assert any(linha["kind"] == "pronto" for linha in eventos(tmp_path / "app.db"))


def test_resumo_sem_identificacao_convida_a_escolher(app_factory):
    at = app_factory()
    at.run()
    navegar(at, "resumo")
    sem_erro(at)
    assert "Primeiro, quem é você?" in " ".join(m.value for m in at.markdown)


def test_trocar_de_pessoa(app_factory):
    at = app_factory()
    at.run()
    navegar(at, "quem")
    at.selectbox(key="select_nome").set_value("Rebecca da Silva Souza")
    at.run()
    botao(at, "✅ Sou eu!").click()
    at.run()
    botao(at, "Trocar de pessoa").click()
    at.run()
    assert at.session_state["person"] == ""


def test_busca_sem_resultado_avisa(app_factory):
    at = app_factory()
    at.run()
    navegar(at, "quem")
    at.text_input(key="busca_nome").set_value("zzzzzz")
    at.run()
    sem_erro(at)
    assert [w.value for w in at.warning]


# ---------------------------------------------------------------------------
# Bloqueio geográfico
# ---------------------------------------------------------------------------


def test_bloqueio_quando_pais_desconhecido_e_estrito(app_factory, tmp_path):
    at = app_factory(GEO_MODE="block", UNKNOWN_COUNTRY_POLICY="block")
    at.run()
    texto = " ".join(m.value for m in at.markdown)
    assert "Acesso restrito" in texto
    assert not at.radio, "não deve existir navegação quando bloqueado"
    assert eventos(tmp_path / "app.db") == []  # sem consentimento, sem log


def test_bloqueio_registra_quando_registro_esta_ligado(app_factory, tmp_path):
    at = app_factory(
        GEO_MODE="block", UNKNOWN_COUNTRY_POLICY="block", CONSENT_REQUIRED="0"
    )
    at.run()
    linhas = eventos(tmp_path / "app.db")
    assert any(linha["kind"] == "blocked" for linha in linhas)


def test_geo_desligado_libera(app_factory):
    at = app_factory(GEO_MODE="off", UNKNOWN_COUNTRY_POLICY="block")
    at.run()
    sem_erro(at)
    assert at.radio, "com geo desligado a navegação aparece"


# ---------------------------------------------------------------------------
# Painel da organização
# ---------------------------------------------------------------------------


def test_admin_fechado_sem_senha(app_factory):
    at = app_factory()
    at.run()
    opcoes = list(at.radio(key="nav").options)
    assert "admin" not in opcoes, "sem senha, o painel nem aparece na navegação"
    sem_erro(at)


def test_admin_abre_com_senha_certa(app_factory):
    at = app_factory(ADMIN_PASSWORD="melancia123")
    at.run()
    navegar(at, "admin")
    at.text_input(key="admin_pw").set_value("errada")
    botao(at, "Entrar").click()
    at.run()
    assert [e.value for e in at.error]

    at.text_input(key="admin_pw").set_value("melancia123")
    botao(at, "Entrar").click()
    at.run()
    sem_erro(at)
    assert at.session_state["admin_ok"] is True
    labels = [m.label for m in at.metric]
    assert "👣 sessões" in labels


def test_admin_mostra_caminho_das_sessoes(app_factory, tmp_path):
    at = app_factory(ADMIN_PASSWORD="melancia123")
    at.run()
    botao(at, "✅ Pode registrar").click()
    at.run()
    navegar(at, "quem")
    navegar(at, "admin")
    at.text_input(key="admin_pw").set_value("melancia123")
    botao(at, "Entrar").click()
    at.run()
    sem_erro(at)
    assert len(at.dataframe) >= 1


# ---------------------------------------------------------------------------
# Meditação
# ---------------------------------------------------------------------------


def test_palavra_positiva_aparece_e_nao_e_gravada(app_factory, tmp_path):
    at = app_factory()
    at.run()
    botao(at, "✅ Pode registrar").click()
    at.run()
    navegar(at, "meditacao")

    segredo = "palavra-secreta-que-nao-deve-ir-pro-banco"
    at.text_input(key="nova_palavra").set_value(segredo)
    botao(at, "Enviar 💌").click()
    at.run()
    sem_erro(at)

    assert segredo in at.session_state["words"]
    assert segredo in " ".join(m.value for m in at.markdown)

    bruto = b"".join(
        arquivo.read_bytes() for arquivo in tmp_path.iterdir() if arquivo.is_file()
    )
    assert segredo.encode() not in bruto


def test_mural_pode_ser_limpo(app_factory):
    at = app_factory()
    at.run()
    navegar(at, "meditacao")
    at.text_input(key="nova_palavra").set_value("vai dar certo")
    botao(at, "Enviar 💌").click()
    at.run()
    botao(at, "🧹 Limpar mural").click()
    at.run()
    assert at.session_state["words"] == []


def test_fotos_da_sessao_nao_vao_para_o_disco(app_factory, tmp_path):
    at = app_factory()
    at.run()
    navegar(at, "meditacao")
    arquivos = {p.name for p in tmp_path.iterdir()}
    assert arquivos <= {"app.db", "app.db-wal", "app.db-shm"}
    assert not any(nome.lower().endswith((".png", ".jpg", ".jpeg", ".webp")) for nome in arquivos)


# ---------------------------------------------------------------------------
# Privacidade
# ---------------------------------------------------------------------------


def test_privacidade_explica_o_que_nao_e_gravado(app_factory):
    at = app_factory()
    at.run()
    navegar(at, "privacidade")
    texto = " ".join(m.value for m in at.markdown).lower()
    assert "nunca é registrado" in texto
    assert "gravação de tela" in texto
    assert "lgpd" in texto or "consentimento" in texto


def test_revogar_consentimento_apaga_os_dados(app_factory, tmp_path):
    at = app_factory()
    at.run()
    botao(at, "✅ Pode registrar").click()
    at.run()
    navegar(at, "quem")
    assert eventos(tmp_path / "app.db")

    navegar(at, "privacidade")
    botao(at, "Revogar consentimento e apagar meus dados").click()
    at.run()
    sem_erro(at)
    assert at.session_state["consent"] == "denied"
    assert eventos(tmp_path / "app.db") == []


def test_pixel_so_aparece_configurado(app_factory):
    at = app_factory(ANALYTICS_PIXEL_URL="https://exemplo.com/p.gif")
    at.run()
    navegar(at, "privacidade")
    texto = " ".join(m.value for m in at.markdown)
    assert "Pixel de acompanhamento" in texto
    assert "https://exemplo.com/p.gif" in texto


# ---------------------------------------------------------------------------
# Robustez
# ---------------------------------------------------------------------------


def test_sid_da_sessao_e_anonimo(app_factory):
    at = app_factory()
    at.run()
    assert app.SID_RE.match(at.session_state["sid"])


def test_paginas_sobrevivem_a_dataset_vazio():
    """Se a planilha vier vazia, nenhuma tela pode explodir."""
    from streamlit.testing.v1 import AppTest

    vazio = '{"monitores": [], "atividades": [], "cronograma": []}'
    fonte = f"""
import json
import app

vazio = json.loads({vazio!r})
app.inject_css()
app.init_state()
app.page_inicio(vazio)
app.page_tarefas(vazio)
app.page_destaques(vazio)
app.page_resumo(app.Settings(), vazio, app.AnalyticsStore(":memory:"), "BR")
"""
    at = AppTest.from_string(fonte, default_timeout=60)
    at.run()
    assert list(at.exception) == []
    assert [e.value for e in at.error] == []


def test_arquivo_unico_e_autossuficiente():
    from conftest import ROOT

    fonte = (ROOT / "app.py").read_text(encoding="utf-8")
    assert "from app import" not in fonte
    assert "import app" not in fonte
    assert "from domain" not in fonte
    assert "st.set_page_config" in fonte
    assert "__DATASET_JSON__" not in fonte


def test_requirements_lista_o_essencial():
    from conftest import ROOT

    requisitos = (ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
    assert "streamlit" in requisitos
    assert "pandas" in requisitos
