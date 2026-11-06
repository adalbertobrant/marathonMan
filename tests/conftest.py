"""Fixtures compartilhadas da suíte.

A ideia: testar a lógica pura (rápido, sem Streamlit) e, em paralelo, subir a
aplicação de verdade com `AppTest` para garantir que nenhuma tela quebra.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app  # noqa: E402  (precisa vir depois do sys.path)

ENV_PREFIXES = (
    "MARATONA_",
    "ADMIN_",
    "GEO_",
    "CONSENT_",
    "ANALYTICS_",
    "ALLOWED_",
    "UNKNOWN_",
    "IP_",
    "ENABLE_",
    "COOKIE_",
    "RETENTION_",
    "PIXEL_",
    "SHEET_",
    "MAX_",
    "TZ_",
    "SURPRESA_",
)


@pytest.fixture(scope="session")
def dataset() -> dict:
    return app.build_dataset()


@pytest.fixture(scope="session")
def monitores(dataset: dict) -> list[dict]:
    return dataset["monitores"]


@pytest.fixture
def cfg() -> app.Settings:
    """Configuração padrão de produção, mas com banco em memória."""
    return app.Settings(db_path=":memory:")


@pytest.fixture
def store(tmp_path: Path):
    instance = app.AnalyticsStore(tmp_path / "eventos.db")
    yield instance
    instance.close()


def _limpar_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith(ENV_PREFIXES):
            monkeypatch.delenv(key, raising=False)


@pytest.fixture
def app_factory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Cria um AppTest isolado (banco próprio e ambiente limpo)."""
    from streamlit.testing.v1 import AppTest

    def _make(**env: str):
        _limpar_env(monkeypatch)
        monkeypatch.setenv("MARATONA_DB", str(tmp_path / "app.db"))
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        return AppTest.from_file(str(ROOT / "app.py"), default_timeout=90)

    return _make


def botao(at, label: str):
    """Acha um botão pelo texto (alguns botões não têm key)."""
    candidatos = [b for b in at.button if b.label == label]
    assert candidatos, f"botão {label!r} não encontrado: {[b.label for b in at.button]}"
    return candidatos[0]


def navegar(at, pagina: str):
    at.radio(key="nav").set_value(pagina)
    return at.run()
