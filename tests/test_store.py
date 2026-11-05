"""Testes do banco de eventos: escrita, retenção, exclusão e privacidade."""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timedelta, timezone

import app

SID = "a" * 32


def test_cria_schema_e_aceita_eventos(store):
    assert store.degraded is False
    assert store.count() == 0
    store.log(SID, "view", screen="inicio", country="BR")
    assert store.count() == 1


def test_tipo_invalido_vira_view(store):
    store.log(SID, "tipo_que_nao_existe", screen="inicio")
    assert store.rows()[0]["kind"] == "view"


def test_eventos_saem_em_ordem_cronologica(store):
    for screen in ("inicio", "quem", "resumo"):
        store.log(SID, "view", screen=screen)
    assert [r["screen"] for r in store.rows()] == ["inicio", "quem", "resumo"]


def test_meta_limita_tamanho(store):
    store.log(SID, "view", screen="inicio", meta={"texto": "x" * 5000})
    meta = store.rows()[0]["meta"]
    assert len(meta) <= 2000


def test_meta_nunca_aceita_conteudo_sensivel_por_engano(store):
    """A API do log só guarda chaves curtas: nada de foto/texto gigante."""
    store.log(SID, "word", screen="meditacao", meta={"total": 3})
    linha = store.rows()[0]
    assert "total" in linha["meta"]
    assert len(linha["meta"]) < 100


def test_schema_nao_tem_coluna_de_ip(store):
    conexao = sqlite3.connect(store.path)
    colunas = [row[1] for row in conexao.execute("PRAGMA table_info(events)")]
    conexao.close()
    assert "ip" not in colunas
    assert "content" not in colunas
    assert set(colunas) == {"id", "ts", "sid", "kind", "screen", "person", "country", "meta"}


def test_retencao_apaga_eventos_antigos(store):
    antigo = (datetime.now(timezone.utc) - timedelta(days=200)).isoformat(timespec="seconds")
    with store._lock:  # inserção direta para simular passado
        store._conn.execute(
            "INSERT INTO events (ts, sid, kind, screen) VALUES (?, ?, ?, ?)",
            (antigo, SID, "view", "inicio"),
        )
        store._conn.commit()
    store.log(SID, "view", screen="quem")
    assert store.count() == 2
    removidos = store.purge(90)
    assert removidos == 1
    assert [r["screen"] for r in store.rows()] == ["quem"]


def test_retencao_com_dias_invalidos_nao_apaga_tudo(store):
    store.log(SID, "view", screen="inicio")
    assert store.purge(0) == 0
    assert store.count() == 1


def test_delete_sid_apaga_so_aquela_sessao(store):
    store.log("a" * 32, "view", screen="inicio")
    store.log("b" * 32, "view", screen="quem")
    assert store.delete_sid("a" * 32) == 1
    assert [r["sid"] for r in store.rows()] == ["b" * 32]


def test_clear_all(store):
    for _ in range(5):
        store.log(SID, "view", screen="inicio")
    assert store.clear_all() == 5
    assert store.count() == 0


def test_export_csv(store):
    store.log(SID, "view", screen="inicio", country="BR", person="Ana")
    texto = store.to_csv()
    linhas = texto.strip().splitlines()
    assert linhas[0] == "ts,sid,kind,screen,person,country,meta"
    assert "inicio" in linhas[1]
    assert "Ana" in linhas[1]


def test_screen_counts(store):
    store.log(SID, "view", screen="inicio")
    store.log(SID, "view", screen="inicio")
    store.log(SID, "view", screen="quem")
    store.log(SID, "leave", screen="quem")
    assert store.screen_counts() == {"inicio": 2, "quem": 1}


def test_blocked_filtra_so_bloqueios(store):
    store.log(SID, "view", screen="inicio")
    store.log(SID, "blocked", country="US", meta={"motivo": "fora da lista"})
    assert len(store.blocked()) == 1
    assert store.blocked()[0]["country"] == "US"


def test_session_paths_agrupa_e_analisa(store):
    store.log(SID, "view", screen="inicio", country="BR")
    store.log(SID, "identify", person="Ana")
    store.log(SID, "view", screen="quem")
    store.log(SID, "view", screen="resumo")
    sessoes = store.session_paths()
    assert len(sessoes) == 1
    sessao = sessoes[0]
    assert sessao["pessoa"] == "Ana"
    assert sessao["pais"] == "BR"
    assert sessao["sequencia"] == ["inicio", "quem", "resumo"]
    assert sessao["status"] == "parcial"
    assert sessao["eventos"] == 4


def test_session_paths_ordena_pela_mais_recente(store):
    store.log("a" * 32, "view", screen="inicio")
    store.log("b" * 32, "view", screen="inicio")
    sessoes = store.session_paths()
    assert sessoes[0]["sid"] == "b" * 32


def test_session_paths_vazio(store):
    assert store.session_paths() == []


def test_escrita_concorrente_nao_perde_evento(store):
    def escrever(indice: int) -> None:
        for _ in range(20):
            store.log(f"{indice:032x}", "view", screen="inicio")

    threads = [threading.Thread(target=escrever, args=(i,)) for i in range(5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert store.count() == 100


def test_banco_sem_permissao_cai_para_memoria(tmp_path):
    ruim = app.AnalyticsStore("/proc/nao-existe-mesmo/eventos.db")
    assert ruim.degraded is True
    ruim.log(SID, "view", screen="inicio")
    assert ruim.count() == 1
    ruim.close()


def test_leitura_de_banco_corrompido_nao_explode(tmp_path):
    caminho = tmp_path / "quebrado.db"
    caminho.write_bytes(b"isto nao e um banco sqlite")
    banco = app.AnalyticsStore(caminho)
    assert banco.rows() == []
    assert banco.count() == 0
    banco.log(SID, "view", screen="inicio")
    banco.close()


def test_utc_now_iso_tem_fuso():
    texto = app.utc_now_iso()
    assert texto.endswith("+00:00")
    assert datetime.fromisoformat(texto).tzinfo is not None
