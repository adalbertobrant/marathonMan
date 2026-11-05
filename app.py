"""Maratona de Melancias 🍉 — painel único da equipe de organização.

Arquivo único, feito para rodar no Streamlit (Streamlit Community Cloud ou local):

    streamlit run app.py

O que tem aqui dentro:
  * visão individual (cada melancia vê só o resumo dela, sem caçar aba no Sheets);
  * mural geral de tarefas com filtros;
  * destaques por horas e parabéns para as melancias;
  * cantinho de meditação (palavras positivas + fotos que NÃO são salvas);
  * transparência de dados (LGPD) e painel da organização.

Regras de privacidade que o código respeita por padrão:
  * nada é registrado antes do consentimento;
  * fotos e palavras da meditação vivem só na sessão do navegador;
  * IP nunca é gravado — só o país, quando disponível;
  * o "pixel" é opcional, aparece na política e só dispara com consentimento.

Licença: MIT.
"""

from __future__ import annotations

import csv
import hashlib
import html
import inspect
import io
import json
import os
import random
import re
import sqlite3
import threading
import time
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence
from urllib.parse import urlencode

import streamlit as st
import streamlit.components.v1 as components

APP_TITLE = "Maratona de Melancias 🍉"
APP_TAGLINE = "a organização mais hidratada do Brasil"

# ---------------------------------------------------------------------------
# Telas e caminho considerado "correto"
# ---------------------------------------------------------------------------

SCREENS: dict[str, tuple[str, str]] = {
    "inicio": ("🍉", "Início"),
    "quem": ("🙋", "Quem é você?"),
    "resumo": ("📋", "Meu resumo"),
    "tarefas": ("🗓️", "Tarefas de todos"),
    "destaques": ("🏆", "Destaques"),
    "meditacao": ("🧘", "Meditação"),
    "pronto": ("✅", "Tô pronto!"),
}

CANONICAL_STEPS: tuple[str, ...] = tuple(SCREENS)

EVENT_DAYS: tuple[date, ...] = (
    date(2026, 11, 5),
    date(2026, 11, 6),
    date(2026, 11, 7),
)

MEDALS = ("🥇", "🥈", "🥉")

# ---------------------------------------------------------------------------
# Configuração (tudo por variável de ambiente; nada sensível no código)
# ---------------------------------------------------------------------------


def _env_flag(value: str | None, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "sim", "yes", "on"}


def _env_int(value: str | None, default: int) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class Settings:
    """Configuração da aplicação, montada a partir do ambiente."""

    db_path: str = ".data/maratona.db"
    geo_mode: str = "block"  # "off" | "block"
    allowed_countries: tuple[str, ...] = ("BR",)
    unknown_country_policy: str = "allow"  # "allow" | "block"
    geo_lookup_url: str = ""  # ex.: "https://ipapi.co/{ip}/country/"
    ip_intel: bool = False
    ip_intel_url: str = "http://ip-api.com/json/{ip}?fields=status,countryCode,proxy,hosting"
    consent_required: bool = True
    cookie_name: str = "melancias_sid"
    cookie_days: int = 30
    retention_days: int = 90
    admin_password: str = ""
    pixel_url: str = ""
    sheet_csv_url: str = ""
    max_photo_mb: int = 8
    tz_name: str = "America/Sao_Paulo"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        e: Mapping[str, str] = os.environ if env is None else env

        def s(key: str, default: str) -> str:
            value = e.get(key)
            return default if value is None or not str(value).strip() else str(value).strip()

        countries = tuple(
            c.strip().upper() for c in s("ALLOWED_COUNTRIES", "BR").split(",") if c.strip()
        )
        geo_mode = s("GEO_MODE", "block").lower()
        if geo_mode not in {"off", "block"}:
            geo_mode = "block"
        unknown_policy = s("UNKNOWN_COUNTRY_POLICY", "allow").lower()
        if unknown_policy not in {"allow", "block"}:
            unknown_policy = "allow"
        return cls(
            db_path=s("MARATONA_DB", ".data/maratona.db"),
            geo_mode=geo_mode,
            allowed_countries=countries or ("BR",),
            unknown_country_policy=unknown_policy,
            geo_lookup_url=s("GEO_LOOKUP_URL", ""),
            ip_intel=_env_flag(e.get("ENABLE_IP_INTEL")),
            ip_intel_url=s(
                "IP_INTEL_URL",
                "http://ip-api.com/json/{ip}?fields=status,countryCode,proxy,hosting",
            ),
            consent_required=_env_flag(e.get("CONSENT_REQUIRED"), True),
            cookie_name=s("COOKIE_NAME", "melancias_sid"),
            cookie_days=_env_int(e.get("COOKIE_DAYS"), 30),
            retention_days=_env_int(e.get("RETENTION_DAYS"), 90),
            admin_password=s("ADMIN_PASSWORD", ""),
            pixel_url=s("ANALYTICS_PIXEL_URL", ""),
            sheet_csv_url=s("SHEET_CSV_URL", ""),
            max_photo_mb=_env_int(e.get("MAX_PHOTO_MB"), 8),
            tz_name=s("TZ_NAME", "America/Sao_Paulo"),
        )


def local_tz(name: str) -> timezone | Any:
    """Fuso de São Paulo, com fallback fixo (-03) se o tzdata faltar."""
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(name)
    except Exception:  # pragma: no cover - depende do sistema
        return timezone(timedelta(hours=-3))


def now_local(cfg: Settings) -> datetime:
    return datetime.now(local_tz(cfg.tz_name))


def to_local(ts: str, cfg: Settings) -> str:
    """Converte um timestamp ISO (UTC) em texto legível no fuso local."""
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return str(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(local_tz(cfg.tz_name)).strftime("%d/%m %H:%M")


# ---------------------------------------------------------------------------
# Dados da escala (snapshot do Google Sheets oficial)
# ---------------------------------------------------------------------------
# O snapshot abaixo é o fallback offline. Para manter atualizado sem editar
# código, defina SHEET_CSV_URL com o link CSV da aba "Alocações".
# A ordem das colunas esperada é: Nome, ID atividade, Data, Início, Fim,
# Atividade, Local, Horas.

DATASET_JSON = r'''{"monitores":[{"nome":"Adalberto Caldeira Brant Filho","lista":"Núcleo (Estatísticas)","reuniao":true,"horas":21.5,"funcoes":7,"dias":[{"dia":"Dia 5 (qui)","itens":[{"ini":"07:00","fim":"12:00","atividade":"Credenciamento (manhã)"},{"ini":"16:30","fim":"19:00","atividade":"Apoio Meninas da Computação"}]},{"dia":"Dia 6 (sex)","itens":[{"ini":"12:00","fim":"13:30","atividade":"Palestras patrocinadores (2º bloco)"},{"ini":"16:30","fim":"19:00","atividade":"Integração - Parque do Sabiá"},{"ini":"19:00","fim":"22:00","atividade":"Jantar + patrocinadores"}]},{"dia":"Dia 7 (sáb)","itens":[{"ini":"08:00","fim":"10:00","atividade":"Café da manhã"},{"ini":"14:00","fim":"19:00","atividade":"Final - competição principal"}]}]},{"nome":"Alexandre Guersoni Dias Resende","lista":"Núcleo (Estatísticas)","reuniao":false,"horas":27.5,"funcoes":7,"dias":[{"dia":"Dia 5 (qui)","itens":[{"ini":"07:00","fim":"12:00","atividade":"Credenciamento (manhã)"},{"ini":"13:00","fim":"17:00","atividade":"Apoio BTG + lanche"},{"ini":"18:00","fim":"22:00","atividade":"Credenciamento (noite)"}]},{"dia":"Dia 6 (sex)","itens":[{"ini":"07:00","fim":"12:00","atividade":"Credenciamento tardio (manhã)"},{"ini":"16:30","fim":"19:00","atividade":"Integração - Parque do Sabiá"}]},{"dia":"Dia 7 (sáb)","itens":[{"ini":"08:00","fim":"10:00","atividade":"Café da manhã"},{"ini":"14:00","fim":"19:00","atividade":"Final - competição principal"}]}]},{"nome":"Ana Clara Serato Rossi De Rezende","lista":"Disponibilidade (extra)","reuniao":false,"horas":8.5,"funcoes":2,"dias":[{"dia":"Dia 5 (qui)","itens":[]},{"dia":"Dia 6 (sex)","itens":[]},{"dia":"Dia 7 (sáb)","itens":[{"ini":"08:00","fim":"11:30","atividade":"Preparação da Arena"},{"ini":"14:00","fim":"19:00","atividade":"Final - competição principal"}]}]},{"nome":"Ana Gabriella Ferreira Ribeiro","lista":"Núcleo (Estatísticas)","reuniao":true,"horas":21.0,"funcoes":7,"dias":[{"dia":"Dia 5 (qui)","itens":[{"ini":"13:00","fim":"17:00","atividade":"Apoio BTG + lanche"}]},{"dia":"Dia 6 (sex)","itens":[{"ini":"12:00","fim":"13:30","atividade":"Palestras patrocinadores (2º bloco)"},{"ini":"14:30","fim":"16:30","atividade":"Montagem integração"},{"ini":"16:30","fim":"19:00","atividade":"Integração - Parque do Sabiá"}]},{"dia":"Dia 7 (sáb)","itens":[{"ini":"08:00","fim":"10:00","atividade":"Café da manhã"},{"ini":"14:00","fim":"19:00","atividade":"Final - competição principal"},{"ini":"19:30","fim":"23:30","atividade":"Jantar de encerramento"}]}]},{"nome":"André Martinez Ribeiro","lista":"Núcleo (Estatísticas)","reuniao":false,"horas":15.0,"funcoes":5,"dias":[{"dia":"Dia 5 (qui)","itens":[]},{"dia":"Dia 6 (sex)","itens":[{"ini":"14:30","fim":"16:30","atividade":"Montagem integração"},{"ini":"16:30","fim":"19:00","atividade":"Integração - Parque do Sabiá"}]},{"dia":"Dia 7 (sáb)","itens":[{"ini":"09:00","fim":"10:30","atividade":"Embarque ônibus (ida)"},{"ini":"14:00","fim":"19:00","atividade":"Final - competição principal"},{"ini":"19:30","fim":"23:30","atividade":"Jantar de encerramento"}]}]},{"nome":"Anna jullia Dos Santos Arêas","lista":"Núcleo (Estatísticas)","reuniao":false,"horas":10.5,"funcoes":3,"dias":[{"dia":"Dia 5 (qui)","itens":[]},{"dia":"Dia 6 (sex)","itens":[]},{"dia":"Dia 7 (sáb)","itens":[{"ini":"09:00","fim":"10:30","atividade":"Embarque ônibus (ida)"},{"ini":"14:00","fim":"19:00","atividade":"Final - competição principal"},{"ini":"19:30","fim":"23:30","atividade":"Jantar de encerramento"}]}]},{"nome":"Clara Magalhães dos Santos","lista":"Disponibilidade (extra)","reuniao":true,"horas":9.0,"funcoes":2,"dias":[{"dia":"Dia 5 (qui)","itens":[]},{"dia":"Dia 6 (sex)","itens":[]},{"dia":"Dia 7 (sáb)","itens":[{"ini":"14:00","fim":"19:00","atividade":"Final - competição principal"},{"ini":"19:30","fim":"23:30","atividade":"Jantar de encerramento"}]}]},{"nome":"Davi Mota Campos","lista":"Núcleo (Estatísticas)","reuniao":false,"horas":21.0,"funcoes":6,"dias":[{"dia":"Dia 5 (qui)","itens":[{"ini":"07:00","fim":"12:00","atividade":"Credenciamento (manhã)"},{"ini":"16:30","fim":"19:00","atividade":"Apoio Meninas da Computação"}]},{"dia":"Dia 6 (sex)","itens":[{"ini":"12:00","fim":"16:30","atividade":"Aquecimento + foto oficial + cachorro-quente"},{"ini":"16:30","fim":"19:00","atividade":"Integração - Parque do Sabiá"}]},{"dia":"Dia 7 (sáb)","itens":[{"ini":"09:00","fim":"10:30","atividade":"Embarque ônibus (ida)"},{"ini":"14:00","fim":"19:00","atividade":"Final - competição principal"}]}]},{"nome":"Diogo Ricarte Loureiro Menezes","lista":"Núcleo (Estatísticas)","reuniao":true,"horas":24.0,"funcoes":6,"dias":[{"dia":"Dia 5 (qui)","itens":[{"ini":"12:00","fim":"18:00","atividade":"Credenciamento (tarde)"},{"ini":"18:30","fim":"22:00","atividade":"Jantar de boas-vindas"}]},{"dia":"Dia 6 (sex)","itens":[{"ini":"12:00","fim":"16:30","atividade":"Aquecimento + foto oficial + cachorro-quente"},{"ini":"19:00","fim":"22:00","atividade":"Jantar + patrocinadores"}]},{"dia":"Dia 7 (sáb)","itens":[{"ini":"11:30","fim":"13:30","atividade":"Almoço"},{"ini":"14:00","fim":"19:00","atividade":"Final - competição principal"}]}]},{"nome":"Débora Cristina Pereira Marra","lista":"Núcleo (Estatísticas)","reuniao":true,"horas":17.0,"funcoes":5,"dias":[{"dia":"Dia 5 (qui)","itens":[{"ini":"12:00","fim":"18:00","atividade":"Credenciamento (tarde)"}]},{"dia":"Dia 6 (sex)","itens":[{"ini":"11:00","fim":"13:00","atividade":"Almoço"},{"ini":"16:30","fim":"19:00","atividade":"Integração - Parque do Sabiá"}]},{"dia":"Dia 7 (sáb)","itens":[{"ini":"09:00","fim":"10:30","atividade":"Embarque ônibus (ida)"},{"ini":"14:00","fim":"19:00","atividade":"Final - kit alimentação e bebidas"}]}]},{"nome":"Eduardo Lordão Oliveira","lista":"Núcleo (Estatísticas)","reuniao":false,"horas":10.5,"funcoes":4,"dias":[{"dia":"Dia 5 (qui)","itens":[{"ini":"18:00","fim":"22:00","atividade":"Credenciamento (noite)"}]},{"dia":"Dia 6 (sex)","itens":[{"ini":"14:30","fim":"16:30","atividade":"Montagem integração"},{"ini":"19:00","fim":"22:00","atividade":"Jantar + patrocinadores"},{"ini":"22:00","fim":"23:30","atividade":"Embarque ônibus (volta)"}]},{"dia":"Dia 7 (sáb)","itens":[]}]},{"nome":"Enzo Santos Fernandes","lista":"Núcleo (Estatísticas)","reuniao":true,"horas":12.5,"funcoes":3,"dias":[{"dia":"Dia 5 (qui)","itens":[]},{"dia":"Dia 6 (sex)","itens":[]},{"dia":"Dia 7 (sáb)","itens":[{"ini":"08:00","fim":"11:30","atividade":"Preparação da Arena"},{"ini":"14:00","fim":"19:00","atividade":"Final - competição principal"},{"ini":"19:30","fim":"23:30","atividade":"Jantar de encerramento"}]}]},{"nome":"Erick da Silva Marques","lista":"Disponibilidade (extra)","reuniao":false,"horas":12.5,"funcoes":3,"dias":[{"dia":"Dia 5 (qui)","itens":[{"ini":"07:00","fim":"12:00","atividade":"Credenciamento (manhã)"},{"ini":"13:00","fim":"17:00","atividade":"Apoio BTG + lanche"},{"ini":"18:30","fim":"22:00","atividade":"Jantar de boas-vindas"}]},{"dia":"Dia 6 (sex)","itens":[]},{"dia":"Dia 7 (sáb)","itens":[]}]},{"nome":"Fred Ferreira Castro","lista":"Disponibilidade (extra)","reuniao":false,"horas":8.5,"funcoes":2,"dias":[{"dia":"Dia 5 (qui)","itens":[]},{"dia":"Dia 6 (sex)","itens":[]},{"dia":"Dia 7 (sáb)","itens":[{"ini":"08:00","fim":"11:30","atividade":"Preparação da Arena"},{"ini":"14:00","fim":"19:00","atividade":"Final - competição principal"}]}]},{"nome":"Gustavo Martinez Ribeiro","lista":"Núcleo (Estatísticas)","reuniao":false,"horas":23.5,"funcoes":7,"dias":[{"dia":"Dia 5 (qui)","itens":[{"ini":"12:00","fim":"18:00","atividade":"Credenciamento (tarde)"},{"ini":"18:30","fim":"22:00","atividade":"Jantar de boas-vindas"}]},{"dia":"Dia 6 (sex)","itens":[{"ini":"16:30","fim":"19:00","atividade":"Integração - Parque do Sabiá"},{"ini":"22:00","fim":"23:30","atividade":"Embarque ônibus (volta)"}]},{"dia":"Dia 7 (sáb)","itens":[{"ini":"08:00","fim":"11:30","atividade":"Preparação da Arena"},{"ini":"14:00","fim":"19:00","atividade":"Final - competição principal"},{"ini":"23:30","fim":"01:00","atividade":"Embarque ônibus (volta)"}]}]},{"nome":"Iara Castro Couto","lista":"Núcleo (Estatísticas)","reuniao":false,"horas":15.5,"funcoes":4,"dias":[{"dia":"Dia 5 (qui)","itens":[]},{"dia":"Dia 6 (sex)","itens":[{"ini":"12:00","fim":"16:30","atividade":"Aquecimento + foto oficial + cachorro-quente"},{"ini":"16:30","fim":"19:00","atividade":"Integração - Parque do Sabiá"}]},{"dia":"Dia 7 (sáb)","itens":[{"ini":"08:00","fim":"11:30","atividade":"Preparação da Arena"},{"ini":"14:00","fim":"19:00","atividade":"Final - competição principal"}]}]},{"nome":"isabela amorim de paula","lista":"Núcleo (Estatísticas)","reuniao":false,"horas":27.5,"funcoes":8,"dias":[{"dia":"Dia 5 (qui)","itens":[{"ini":"07:00","fim":"12:00","atividade":"Credenciamento (manhã)"},{"ini":"13:00","fim":"17:00","atividade":"Apoio BTG + lanche"},{"ini":"18:30","fim":"22:00","atividade":"Jantar de boas-vindas"}]},{"dia":"Dia 6 (sex)","itens":[{"ini":"07:00","fim":"08:30","atividade":"Embarque ônibus (ida)"},{"ini":"12:00","fim":"16:30","atividade":"Aquecimento + foto oficial + cachorro-quente"},{"ini":"16:30","fim":"19:00","atividade":"Integração - Parque do Sabiá"}]},{"dia":"Dia 7 (sáb)","itens":[{"ini":"09:00","fim":"10:30","atividade":"Embarque ônibus (ida)"},{"ini":"14:00","fim":"19:00","atividade":"Final - competição principal"}]}]},{"nome":"Isabela Cunha Silva","lista":"Núcleo (Estatísticas)","reuniao":true,"horas":29.5,"funcoes":8,"dias":[{"dia":"Dia 5 (qui)","itens":[{"ini":"07:00","fim":"12:00","atividade":"Credenciamento (manhã)"},{"ini":"12:00","fim":"18:00","atividade":"Credenciamento (tarde)"},{"ini":"18:30","fim":"22:00","atividade":"Jantar de boas-vindas"}]},{"dia":"Dia 6 (sex)","itens":[{"ini":"05:30","fim":"08:00","atividade":"Café da manhã"},{"ini":"16:30","fim":"19:00","atividade":"Integração - Parque do Sabiá"}]},{"dia":"Dia 7 (sáb)","itens":[{"ini":"08:00","fim":"11:30","atividade":"Preparação da Arena"},{"ini":"14:00","fim":"19:00","atividade":"Final - competição principal"},{"ini":"23:30","fim":"01:00","atividade":"Embarque ônibus (volta)"}]}]},{"nome":"Istéfane de souza","lista":"Núcleo (Estatísticas)","reuniao":false,"horas":23.5,"funcoes":6,"dias":[{"dia":"Dia 5 (qui)","itens":[{"ini":"12:00","fim":"18:00","atividade":"Credenciamento (tarde)"},{"ini":"18:30","fim":"22:00","atividade":"Jantar de boas-vindas"}]},{"dia":"Dia 6 (sex)","itens":[{"ini":"12:00","fim":"16:30","atividade":"Aquecimento + foto oficial + cachorro-quente"},{"ini":"16:30","fim":"19:00","atividade":"Integração - Parque do Sabiá"}]},{"dia":"Dia 7 (sáb)","itens":[{"ini":"08:00","fim":"10:00","atividade":"Café da manhã"},{"ini":"14:00","fim":"19:00","atividade":"Final - competição principal"}]}]},{"nome":"Jhon Waine Mendes Gonçalves","lista":"Núcleo (Estatísticas)","reuniao":false,"horas":15.0,"funcoes":4,"dias":[{"dia":"Dia 5 (qui)","itens":[]},{"dia":"Dia 6 (sex)","itens":[{"ini":"16:30","fim":"19:00","atividade":"Integração - Parque do Sabiá"}]},{"dia":"Dia 7 (sáb)","itens":[{"ini":"08:00","fim":"11:30","atividade":"Preparação da Arena"},{"ini":"14:00","fim":"19:00","atividade":"Final - competição principal"},{"ini":"19:30","fim":"23:30","atividade":"Jantar de encerramento"}]}]},{"nome":"João Gabriel Santos Nunes","lista":"Núcleo (Estatísticas)","reuniao":false,"horas":12.5,"funcoes":3,"dias":[{"dia":"Dia 5 (qui)","itens":[]},{"dia":"Dia 6 (sex)","itens":[]},{"dia":"Dia 7 (sáb)","itens":[{"ini":"08:00","fim":"11:30","atividade":"Preparação da Arena"},{"ini":"14:00","fim":"19:00","atividade":"Final - competição principal"},{"ini":"19:30","fim":"23:30","atividade":"Jantar de encerramento"}]}]},{"nome":"João Pedro Cardoso de Oliveira","lista":"Disponibilidade (extra)","reuniao":false,"horas":16.5,"funcoes":4,"dias":[{"dia":"Dia 5 (qui)","itens":[{"ini":"12:00","fim":"18:00","atividade":"Credenciamento (tarde)"}]},{"dia":"Dia 6 (sex)","itens":[{"ini":"12:00","fim":"15:00","atividade":"Credenciamento tardio (tarde)"},{"ini":"16:30","fim":"19:00","atividade":"Integração - Parque do Sabiá"}]},{"dia":"Dia 7 (sáb)","itens":[{"ini":"14:00","fim":"19:00","atividade":"Final - competição principal"}]}]},{"nome":"João Pedro de Oliveira Gomes","lista":"Núcleo (Estatísticas)","reuniao":true,"horas":21.0,"funcoes":6,"dias":[{"dia":"Dia 5 (qui)","itens":[{"ini":"12:00","fim":"18:00","atividade":"Credenciamento (tarde)"},{"ini":"18:30","fim":"22:00","atividade":"Jantar de boas-vindas"}]},{"dia":"Dia 6 (sex)","itens":[{"ini":"11:00","fim":"13:00","atividade":"Almoço"},{"ini":"16:30","fim":"19:00","atividade":"Integração - Parque do Sabiá"}]},{"dia":"Dia 7 (sáb)","itens":[{"ini":"11:30","fim":"13:30","atividade":"Almoço"},{"ini":"14:00","fim":"19:00","atividade":"Final - competição principal"}]}]},{"nome":"Júlia Marques Santos","lista":"Núcleo (Estatísticas)","reuniao":true,"horas":21.5,"funcoes":6,"dias":[{"dia":"Dia 5 (qui)","itens":[{"ini":"13:00","fim":"17:00","atividade":"Apoio BTG + lanche"},{"ini":"18:30","fim":"22:00","atividade":"Jantar de boas-vindas"}]},{"dia":"Dia 6 (sex)","itens":[{"ini":"16:30","fim":"19:00","atividade":"Integração - Parque do Sabiá"},{"ini":"19:00","fim":"22:00","atividade":"Jantar + patrocinadores"}]},{"dia":"Dia 7 (sáb)","itens":[{"ini":"08:00","fim":"11:30","atividade":"Preparação da Arena"},{"ini":"14:00","fim":"19:00","atividade":"Final - competição principal"}]}]},{"nome":"Kamylla Machado Rezende","lista":"Núcleo (Estatísticas)","reuniao":false,"horas":17.0,"funcoes":5,"dias":[{"dia":"Dia 5 (qui)","itens":[]},{"dia":"Dia 6 (sex)","itens":[{"ini":"14:30","fim":"16:30","atividade":"Montagem integração"},{"ini":"16:30","fim":"19:00","atividade":"Integração - Parque do Sabiá"}]},{"dia":"Dia 7 (sáb)","itens":[{"ini":"08:00","fim":"11:30","atividade":"Preparação da Arena"},{"ini":"14:00","fim":"19:00","atividade":"Final - competição principal"},{"ini":"19:30","fim":"23:30","atividade":"Jantar de encerramento"}]}]},{"nome":"Karolyne Cardoso Magalhães","lista":"Disponibilidade (extra)","reuniao":false,"horas":9.0,"funcoes":3,"dias":[{"dia":"Dia 5 (qui)","itens":[]},{"dia":"Dia 6 (sex)","itens":[{"ini":"11:00","fim":"13:00","atividade":"Almoço"}]},{"dia":"Dia 7 (sáb)","itens":[{"ini":"11:30","fim":"13:30","atividade":"Almoço"},{"ini":"14:00","fim":"19:00","atividade":"Final - competição principal"}]}]},{"nome":"Karyna Silva Leite","lista":"Disponibilidade (extra)","reuniao":false,"horas":8.5,"funcoes":2,"dias":[{"dia":"Dia 5 (qui)","itens":[]},{"dia":"Dia 6 (sex)","itens":[]},{"dia":"Dia 7 (sáb)","itens":[{"ini":"08:00","fim":"11:30","atividade":"Preparação da Arena"},{"ini":"14:00","fim":"19:00","atividade":"Final - competição principal"}]}]},{"nome":"Leandro Henrique Silva Rabelo","lista":"Núcleo (Estatísticas)","reuniao":true,"horas":25.0,"funcoes":7,"dias":[{"dia":"Dia 5 (qui)","itens":[{"ini":"07:00","fim":"12:00","atividade":"Credenciamento (manhã)"},{"ini":"16:30","fim":"19:00","atividade":"Apoio Meninas da Computação"}]},{"dia":"Dia 6 (sex)","itens":[{"ini":"08:00","fim":"11:30","atividade":"Palestras patrocinadores (1º bloco)"},{"ini":"16:30","fim":"19:00","atividade":"Integração - Parque do Sabiá"},{"ini":"19:00","fim":"22:00","atividade":"Jantar + patrocinadores"}]},{"dia":"Dia 7 (sáb)","itens":[{"ini":"08:00","fim":"11:30","atividade":"Preparação da Arena"},{"ini":"14:00","fim":"19:00","atividade":"Final - competição principal"}]}]},{"nome":"Lethicia Ferreira de Almeida","lista":"Disponibilidade (extra)","reuniao":false,"horas":8.5,"funcoes":2,"dias":[{"dia":"Dia 5 (qui)","itens":[]},{"dia":"Dia 6 (sex)","itens":[]},{"dia":"Dia 7 (sáb)","itens":[{"ini":"08:00","fim":"11:30","atividade":"Preparação da Arena"},{"ini":"14:00","fim":"19:00","atividade":"Final - competição principal"}]}]},{"nome":"Letícia Moura Lemos","lista":"Núcleo (Estatísticas)","reuniao":false,"horas":18.0,"funcoes":5,"dias":[{"dia":"Dia 5 (qui)","itens":[{"ini":"07:00","fim":"12:00","atividade":"Credenciamento (manhã)"}]},{"dia":"Dia 6 (sex)","itens":[{"ini":"08:00","fim":"11:30","atividade":"Palestras patrocinadores (1º bloco)"},{"ini":"16:30","fim":"19:00","atividade":"Integração - Parque do Sabiá"}]},{"dia":"Dia 7 (sáb)","itens":[{"ini":"08:00","fim":"10:00","atividade":"Café da manhã"},{"ini":"14:00","fim":"19:00","atividade":"Final - competição principal"}]}]},{"nome":"Luciana Ferreira dos Santos","lista":"Núcleo (Estatísticas)","reuniao":true,"horas":12.5,"funcoes":3,"dias":[{"dia":"Dia 5 (qui)","itens":[]},{"dia":"Dia 6 (sex)","itens":[]},{"dia":"Dia 7 (sáb)","itens":[{"ini":"08:00","fim":"11:30","atividade":"Preparação da Arena"},{"ini":"14:00","fim":"19:00","atividade":"Final - competição principal"},{"ini":"19:30","fim":"23:30","atividade":"Jantar de encerramento"}]}]},{"nome":"Maria Cecília Rodrigues Oliveira Rosa","lista":"Núcleo (Estatísticas)","reuniao":true,"horas":13.5,"funcoes":4,"dias":[{"dia":"Dia 5 (qui)","itens":[]},{"dia":"Dia 6 (sex)","itens":[{"ini":"16:30","fim":"19:00","atividade":"Integração - Parque do Sabiá"}]},{"dia":"Dia 7 (sáb)","itens":[{"ini":"11:30","fim":"13:30","atividade":"Almoço"},{"ini":"14:00","fim":"19:00","atividade":"Final - competição principal"},{"ini":"19:30","fim":"23:30","atividade":"Jantar de encerramento"}]}]},{"nome":"Mariana Pinheiro Zanon","lista":"Disponibilidade (extra)","reuniao":false,"horas":11.0,"funcoes":3,"dias":[{"dia":"Dia 5 (qui)","itens":[]},{"dia":"Dia 6 (sex)","itens":[{"ini":"05:30","fim":"08:00","atividade":"Café da manhã"}]},{"dia":"Dia 7 (sáb)","itens":[{"ini":"08:00","fim":"11:30","atividade":"Preparação da Arena"},{"ini":"14:00","fim":"19:00","atividade":"Final - competição principal"}]}]},{"nome":"Matheus Cardoso Miranda","lista":"Núcleo (Estatísticas)","reuniao":true,"horas":23.5,"funcoes":6,"dias":[{"dia":"Dia 5 (qui)","itens":[{"ini":"07:00","fim":"12:00","atividade":"Credenciamento (manhã)"},{"ini":"18:00","fim":"22:00","atividade":"Credenciamento (noite)"}]},{"dia":"Dia 6 (sex)","itens":[{"ini":"07:00","fim":"12:00","atividade":"Credenciamento tardio (manhã)"},{"ini":"16:30","fim":"19:00","atividade":"Integração - Parque do Sabiá"}]},{"dia":"Dia 7 (sáb)","itens":[{"ini":"08:00","fim":"10:00","atividade":"Café da manhã"},{"ini":"14:00","fim":"19:00","atividade":"Final - competição principal"}]}]},{"nome":"Matheus Gualter Silva Resende","lista":"Núcleo (Estatísticas)","reuniao":true,"horas":19.0,"funcoes":6,"dias":[{"dia":"Dia 5 (qui)","itens":[{"ini":"13:00","fim":"17:00","atividade":"Apoio BTG + lanche"},{"ini":"18:30","fim":"22:00","atividade":"Jantar de boas-vindas"}]},{"dia":"Dia 6 (sex)","itens":[{"ini":"11:00","fim":"13:00","atividade":"Almoço"},{"ini":"16:30","fim":"19:00","atividade":"Integração - Parque do Sabiá"}]},{"dia":"Dia 7 (sáb)","itens":[{"ini":"11:30","fim":"13:30","atividade":"Almoço"},{"ini":"14:00","fim":"19:00","atividade":"Final - competição principal"}]}]},{"nome":"Melissa Oliveira Nobre","lista":"Núcleo (Estatísticas)","reuniao":true,"horas":25.5,"funcoes":8,"dias":[{"dia":"Dia 5 (qui)","itens":[{"ini":"07:00","fim":"12:00","atividade":"Credenciamento (manhã)"},{"ini":"16:30","fim":"19:00","atividade":"Apoio Meninas da Computação"}]},{"dia":"Dia 6 (sex)","itens":[{"ini":"05:30","fim":"08:00","atividade":"Café da manhã"},{"ini":"12:00","fim":"15:00","atividade":"Credenciamento tardio (tarde)"},{"ini":"16:30","fim":"19:00","atividade":"Integração - Parque do Sabiá"},{"ini":"19:00","fim":"22:00","atividade":"Jantar + patrocinadores"}]},{"dia":"Dia 7 (sáb)","itens":[{"ini":"11:30","fim":"13:30","atividade":"Almoço"},{"ini":"14:00","fim":"19:00","atividade":"Final - competição principal"}]}]},{"nome":"Miguel Pereira Borges","lista":"Núcleo (Estatísticas)","reuniao":true,"horas":16.0,"funcoes":5,"dias":[{"dia":"Dia 5 (qui)","itens":[{"ini":"13:00","fim":"17:00","atividade":"Apoio BTG + lanche"}]},{"dia":"Dia 6 (sex)","itens":[{"ini":"05:30","fim":"08:00","atividade":"Café da manhã"},{"ini":"14:30","fim":"16:30","atividade":"Montagem integração"},{"ini":"16:30","fim":"19:00","atividade":"Integração - Parque do Sabiá"}]},{"dia":"Dia 7 (sáb)","itens":[{"ini":"14:00","fim":"19:00","atividade":"Final - kit alimentação e bebidas"}]}]},{"nome":"Nicolas Honorato Lima","lista":"Núcleo (Estatísticas)","reuniao":false,"horas":8.5,"funcoes":2,"dias":[{"dia":"Dia 5 (qui)","itens":[]},{"dia":"Dia 6 (sex)","itens":[]},{"dia":"Dia 7 (sáb)","itens":[{"ini":"08:00","fim":"11:30","atividade":"Preparação da Arena"},{"ini":"14:00","fim":"19:00","atividade":"Final - competição principal"}]}]},{"nome":"Nicolly Ribeiro Luz","lista":"Núcleo (Estatísticas)","reuniao":true,"horas":21.0,"funcoes":6,"dias":[{"dia":"Dia 5 (qui)","itens":[{"ini":"12:00","fim":"18:00","atividade":"Credenciamento (tarde)"},{"ini":"18:30","fim":"22:00","atividade":"Jantar de boas-vindas"}]},{"dia":"Dia 6 (sex)","itens":[{"ini":"12:00","fim":"13:30","atividade":"Palestras patrocinadores (2º bloco)"},{"ini":"19:00","fim":"22:00","atividade":"Jantar + patrocinadores"}]},{"dia":"Dia 7 (sáb)","itens":[{"ini":"11:30","fim":"13:30","atividade":"Almoço"},{"ini":"14:00","fim":"19:00","atividade":"Final - competição principal"}]}]},{"nome":"Pedro Henrique Vieira Pinto","lista":"Núcleo (Estatísticas)","reuniao":false,"horas":24.0,"funcoes":7,"dias":[{"dia":"Dia 5 (qui)","itens":[{"ini":"13:00","fim":"17:00","atividade":"Apoio BTG + lanche"},{"ini":"18:00","fim":"22:00","atividade":"Credenciamento (noite)"}]},{"dia":"Dia 6 (sex)","itens":[{"ini":"08:00","fim":"11:30","atividade":"Palestras patrocinadores (1º bloco)"},{"ini":"16:30","fim":"19:00","atividade":"Integração - Parque do Sabiá"},{"ini":"19:00","fim":"22:00","atividade":"Jantar + patrocinadores"}]},{"dia":"Dia 7 (sáb)","itens":[{"ini":"11:30","fim":"13:30","atividade":"Almoço"},{"ini":"14:00","fim":"19:00","atividade":"Final - competição principal"}]}]},{"nome":"Raul Gustavo Cavalcante Maia","lista":"Núcleo (Estatísticas)","reuniao":true,"horas":22.5,"funcoes":7,"dias":[{"dia":"Dia 5 (qui)","itens":[{"ini":"07:00","fim":"12:00","atividade":"Credenciamento (manhã)"},{"ini":"16:30","fim":"19:00","atividade":"Apoio Meninas da Computação"}]},{"dia":"Dia 6 (sex)","itens":[{"ini":"07:00","fim":"08:30","atividade":"Embarque ônibus (ida)"},{"ini":"16:30","fim":"19:00","atividade":"Integração - Parque do Sabiá"}]},{"dia":"Dia 7 (sáb)","itens":[{"ini":"11:30","fim":"13:30","atividade":"Almoço"},{"ini":"14:00","fim":"19:00","atividade":"Final - competição principal"},{"ini":"19:30","fim":"23:30","atividade":"Jantar de encerramento"}]}]},{"nome":"Rayssa Pereira da Silva","lista":"Disponibilidade (extra)","reuniao":false,"horas":3.5,"funcoes":1,"dias":[{"dia":"Dia 5 (qui)","itens":[]},{"dia":"Dia 6 (sex)","itens":[]},{"dia":"Dia 7 (sáb)","itens":[{"ini":"08:00","fim":"11:30","atividade":"Preparação da Arena"}]}]},{"nome":"Rebecca da Silva Souza","lista":"Núcleo (Estatísticas)","reuniao":true,"horas":33.5,"funcoes":8,"dias":[{"dia":"Dia 5 (qui)","itens":[{"ini":"07:00","fim":"12:00","atividade":"Credenciamento (manhã)"},{"ini":"12:00","fim":"18:00","atividade":"Credenciamento (tarde)"},{"ini":"18:30","fim":"22:00","atividade":"Jantar de boas-vindas"}]},{"dia":"Dia 6 (sex)","itens":[{"ini":"07:00","fim":"12:00","atividade":"Credenciamento tardio (manhã)"},{"ini":"12:00","fim":"16:30","atividade":"Aquecimento + foto oficial + cachorro-quente"},{"ini":"16:30","fim":"19:00","atividade":"Integração - Parque do Sabiá"}]},{"dia":"Dia 7 (sáb)","itens":[{"ini":"11:30","fim":"13:30","atividade":"Almoço"},{"ini":"14:00","fim":"19:00","atividade":"Final - kit alimentação e bebidas"}]}]},{"nome":"Rhuan Henrique De Oliveira Ramos","lista":"Núcleo (Estatísticas)","reuniao":false,"horas":27.5,"funcoes":7,"dias":[{"dia":"Dia 5 (qui)","itens":[{"ini":"12:00","fim":"18:00","atividade":"Credenciamento (tarde)"},{"ini":"18:30","fim":"22:00","atividade":"Jantar de boas-vindas"}]},{"dia":"Dia 6 (sex)","itens":[{"ini":"07:00","fim":"12:00","atividade":"Credenciamento tardio (manhã)"},{"ini":"12:00","fim":"15:00","atividade":"Credenciamento tardio (tarde)"},{"ini":"19:00","fim":"22:00","atividade":"Jantar + patrocinadores"}]},{"dia":"Dia 7 (sáb)","itens":[{"ini":"11:30","fim":"13:30","atividade":"Almoço"},{"ini":"14:00","fim":"19:00","atividade":"Final - competição principal"}]}]},{"nome":"Rogério Anastácio","lista":"Disponibilidade (extra)","reuniao":true,"horas":5.0,"funcoes":2,"dias":[{"dia":"Dia 5 (qui)","itens":[]},{"dia":"Dia 6 (sex)","itens":[{"ini":"22:00","fim":"23:30","atividade":"Embarque ônibus (volta)"}]},{"dia":"Dia 7 (sáb)","itens":[{"ini":"08:00","fim":"11:30","atividade":"Preparação da Arena"}]}]},{"nome":"Samuel Victor Alventino Silva","lista":"Núcleo (Estatísticas)","reuniao":true,"horas":27.0,"funcoes":9,"dias":[{"dia":"Dia 5 (qui)","itens":[{"ini":"07:00","fim":"12:00","atividade":"Credenciamento (manhã)"},{"ini":"13:00","fim":"17:00","atividade":"Apoio BTG + lanche"},{"ini":"18:30","fim":"22:00","atividade":"Jantar de boas-vindas"}]},{"dia":"Dia 6 (sex)","itens":[{"ini":"07:00","fim":"08:30","atividade":"Embarque ônibus (ida)"},{"ini":"11:00","fim":"13:00","atividade":"Almoço"},{"ini":"16:30","fim":"19:00","atividade":"Integração - Parque do Sabiá"}]},{"dia":"Dia 7 (sáb)","itens":[{"ini":"11:30","fim":"13:30","atividade":"Almoço"},{"ini":"14:00","fim":"19:00","atividade":"Final - competição principal"},{"ini":"23:30","fim":"01:00","atividade":"Embarque ônibus (volta)"}]}]},{"nome":"Victor da Costa Mota","lista":"Núcleo (Estatísticas)","reuniao":false,"horas":11.0,"funcoes":3,"dias":[{"dia":"Dia 5 (qui)","itens":[]},{"dia":"Dia 6 (sex)","itens":[]},{"dia":"Dia 7 (sáb)","itens":[{"ini":"11:30","fim":"13:30","atividade":"Almoço"},{"ini":"14:00","fim":"19:00","atividade":"Final - competição principal"},{"ini":"19:30","fim":"23:30","atividade":"Jantar de encerramento"}]}]},{"nome":"Vinícius Albino Torres Lima","lista":"Núcleo (Estatísticas)","reuniao":true,"horas":21.5,"funcoes":6,"dias":[{"dia":"Dia 5 (qui)","itens":[{"ini":"13:00","fim":"17:00","atividade":"Apoio BTG + lanche"},{"ini":"18:30","fim":"22:00","atividade":"Jantar de boas-vindas"}]},{"dia":"Dia 6 (sex)","itens":[{"ini":"12:00","fim":"16:30","atividade":"Aquecimento + foto oficial + cachorro-quente"},{"ini":"16:30","fim":"19:00","atividade":"Integração - Parque do Sabiá"}]},{"dia":"Dia 7 (sáb)","itens":[{"ini":"11:30","fim":"13:30","atividade":"Almoço"},{"ini":"14:00","fim":"19:00","atividade":"Final - kit alimentação e bebidas"}]}]},{"nome":"vitor eduardo gonçalves vasconcelos","lista":"Disponibilidade (extra)","reuniao":false,"horas":14.0,"funcoes":4,"dias":[{"dia":"Dia 5 (qui)","itens":[{"ini":"18:00","fim":"22:00","atividade":"Credenciamento (noite)"}]},{"dia":"Dia 6 (sex)","itens":[{"ini":"19:00","fim":"22:00","atividade":"Jantar + patrocinadores"}]},{"dia":"Dia 7 (sáb)","itens":[{"ini":"11:30","fim":"13:30","atividade":"Almoço"},{"ini":"14:00","fim":"19:00","atividade":"Final - competição principal"}]}]},{"nome":"Vitória Gabrielly Souza Vieira","lista":"Disponibilidade (extra)","reuniao":false,"horas":13.5,"funcoes":4,"dias":[{"dia":"Dia 5 (qui)","itens":[{"ini":"18:00","fim":"22:00","atividade":"Credenciamento (noite)"}]},{"dia":"Dia 6 (sex)","itens":[{"ini":"16:30","fim":"19:00","atividade":"Integração - Parque do Sabiá"}]},{"dia":"Dia 7 (sáb)","itens":[{"ini":"11:30","fim":"13:30","atividade":"Almoço"},{"ini":"14:00","fim":"19:00","atividade":"Final - competição principal"}]}]},{"nome":"Laura Prado Correia","lista":"Reserva","reuniao":false,"horas":14.0,"funcoes":4,"dias":[{"dia":"Dia 5 (qui)","itens":[]},{"dia":"Dia 6 (sex)","itens":[{"ini":"12:00","fim":"13:30","atividade":"Palestras patrocinadores (2º bloco)"}]},{"dia":"Dia 7 (sáb)","itens":[{"ini":"08:00","fim":"11:30","atividade":"Preparação da Arena"},{"ini":"14:00","fim":"19:00","atividade":"Final - competição principal"},{"ini":"19:30","fim":"23:30","atividade":"Jantar de encerramento"}]}]},{"nome":"Luisa Egert Teixeira","lista":"Reserva","reuniao":false,"horas":12.5,"funcoes":3,"dias":[{"dia":"Dia 5 (qui)","itens":[]},{"dia":"Dia 6 (sex)","itens":[]},{"dia":"Dia 7 (sáb)","itens":[{"ini":"08:00","fim":"11:30","atividade":"Preparação da Arena"},{"ini":"14:00","fim":"19:00","atividade":"Final - kit alimentação e bebidas"},{"ini":"19:30","fim":"23:30","atividade":"Jantar de encerramento"}]}]}],"atividades":[{"id":"D5-01","data":"05/11/2026","dia":"Quinta-feira","ini":"07:00","fim":"12:00","atividade":"Credenciamento, fotos dos times e entrega de materiais (manhã)","local":"Hotel Porto Minas – Sala 05","vagas":13,"escalados":13,"monitores":["Adalberto Caldeira Brant Filho","Alexandre Guersoni Dias Resende","Davi Mota Campos","Erick da Silva Marques","isabela amorim de paula","Isabela Cunha Silva","Leandro Henrique Silva Rabelo","Letícia Moura Lemos","Matheus Cardoso Miranda","Melissa Oliveira Nobre","Raul Gustavo Cavalcante Maia","Rebecca da Silva Souza","Samuel Victor Alventino Silva"]},{"id":"D5-02","data":"05/11/2026","dia":"Quinta-feira","ini":"12:00","fim":"18:00","atividade":"Credenciamento e entrega de materiais (tarde)","local":"Hotel Porto Minas – Sala 05","vagas":10,"escalados":10,"monitores":["Débora Cristina Pereira Marra","Diogo Ricarte Loureiro Menezes","Gustavo Martinez Ribeiro","Isabela Cunha Silva","Istéfane de souza","João Pedro Cardoso de Oliveira","João Pedro de Oliveira Gomes","Nicolly Ribeiro Luz","Rebecca da Silva Souza","Rhuan Henrique De Oliveira Ramos"]},{"id":"D5-03","data":"05/11/2026","dia":"Quinta-feira","ini":"13:00","fim":"17:00","atividade":"Apoio BTG + lanche BTG (16h–17h)","local":"Hotel Porto Minas – Sala 05","vagas":10,"escalados":10,"monitores":["Alexandre Guersoni Dias Resende","Ana Gabriella Ferreira Ribeiro","Erick da Silva Marques","isabela amorim de paula","Júlia Marques Santos","Matheus Gualter Silva Resende","Miguel Pereira Borges","Pedro Henrique Vieira Pinto","Samuel Victor Alventino Silva","Vinícius Albino Torres Lima"]},{"id":"D5-04","data":"05/11/2026","dia":"Quinta-feira","ini":"16:30","fim":"19:00","atividade":"Apoio Meninas da Computação","local":"Hotel Porto Minas – Sala 01","vagas":5,"escalados":5,"monitores":["Adalberto Caldeira Brant Filho","Davi Mota Campos","Leandro Henrique Silva Rabelo","Melissa Oliveira Nobre","Raul Gustavo Cavalcante Maia"]},{"id":"D5-05","data":"05/11/2026","dia":"Quinta-feira","ini":"18:00","fim":"22:00","atividade":"Credenciamento (noite)","local":"Hotel Porto Minas – Sala 05","vagas":6,"escalados":6,"monitores":["Alexandre Guersoni Dias Resende","Eduardo Lordão Oliveira","Matheus Cardoso Miranda","Pedro Henrique Vieira Pinto","vitor eduardo gonçalves vasconcelos","Vitória Gabrielly Souza Vieira"]},{"id":"D5-06","data":"05/11/2026","dia":"Quinta-feira","ini":"18:30","fim":"22:00","atividade":"Apoio Jantar de Boas-Vindas","local":"Hotel Porto Minas – Sala 05","vagas":14,"escalados":14,"monitores":["Diogo Ricarte Loureiro Menezes","Erick da Silva Marques","Gustavo Martinez Ribeiro","isabela amorim de paula","Isabela Cunha Silva","Istéfane de souza","João Pedro de Oliveira Gomes","Júlia Marques Santos","Matheus Gualter Silva Resende","Nicolly Ribeiro Luz","Rebecca da Silva Souza","Rhuan Henrique De Oliveira Ramos","Samuel Victor Alventino Silva","Vinícius Albino Torres Lima"]},{"id":"D6-01","data":"06/11/2026","dia":"Sexta-feira","ini":"05:30","fim":"08:00","atividade":"Apoio Café da manhã (Grupo 1 06h, Grupo 2 07h)","local":"Hotel Porto Minas – Restaurante","vagas":4,"escalados":4,"monitores":["Isabela Cunha Silva","Mariana Pinheiro Zanon","Melissa Oliveira Nobre","Miguel Pereira Borges"]},{"id":"D6-02","data":"06/11/2026","dia":"Sexta-feira","ini":"07:00","fim":"08:30","atividade":"Apoio Deslocamentos – embarque (G1 07h, G2 08h)","local":"Hotel Porto Minas – Rua lateral","vagas":3,"escalados":3,"monitores":["isabela amorim de paula","Raul Gustavo Cavalcante Maia","Samuel Victor Alventino Silva"]},{"id":"D6-03","data":"06/11/2026","dia":"Sexta-feira","ini":"07:00","fim":"12:00","atividade":"Credenciamento tardio e entrega de materiais (manhã)","local":"Arena Sabiazinho","vagas":4,"escalados":4,"monitores":["Alexandre Guersoni Dias Resende","Matheus Cardoso Miranda","Rebecca da Silva Souza","Rhuan Henrique De Oliveira Ramos"]},{"id":"D6-04","data":"06/11/2026","dia":"Sexta-feira","ini":"08:00","fim":"11:30","atividade":"Apoio palestras / integração com patrocinadores (1º bloco)","local":"Arquibancada Arena Sabiazinho","vagas":3,"escalados":3,"monitores":["Leandro Henrique Silva Rabelo","Letícia Moura Lemos","Pedro Henrique Vieira Pinto"]},{"id":"D6-05","data":"06/11/2026","dia":"Sexta-feira","ini":"11:00","fim":"13:00","atividade":"Apoio Almoço","local":"Estádio Parque do Sabiá – Portão 06","vagas":5,"escalados":5,"monitores":["Débora Cristina Pereira Marra","João Pedro de Oliveira Gomes","Karolyne Cardoso Magalhães","Matheus Gualter Silva Resende","Samuel Victor Alventino Silva"]},{"id":"D6-06","data":"06/11/2026","dia":"Sexta-feira","ini":"12:00","fim":"15:00","atividade":"Credenciamento tardio (tarde)","local":"Arena Sabiazinho","vagas":3,"escalados":3,"monitores":["João Pedro Cardoso de Oliveira","Melissa Oliveira Nobre","Rhuan Henrique De Oliveira Ramos"]},{"id":"D6-07","data":"06/11/2026","dia":"Sexta-feira","ini":"12:00","fim":"13:30","atividade":"Apoio palestras / patrocinadores (2º bloco)","local":"Arquibancada Arena Sabiazinho","vagas":4,"escalados":4,"monitores":["Adalberto Caldeira Brant Filho","Ana Gabriella Ferreira Ribeiro","Laura Prado Correia","Nicolly Ribeiro Luz"]},{"id":"D6-08","data":"06/11/2026","dia":"Sexta-feira","ini":"12:00","fim":"16:30","atividade":"Aquecimento (warm-up), 1ª foto oficial (15h30) e cachorro-quente nas tendas","local":"Arena Sabiazinho","vagas":7,"escalados":7,"monitores":["Davi Mota Campos","Diogo Ricarte Loureiro Menezes","Iara Castro Couto","isabela amorim de paula","Istéfane de souza","Rebecca da Silva Souza","Vinícius Albino Torres Lima"]},{"id":"D6-09","data":"06/11/2026","dia":"Sexta-feira","ini":"14:30","fim":"16:30","atividade":"Montagem e preparação da atividade de integração","local":"Parque do Sabiá","vagas":5,"escalados":5,"monitores":["Ana Gabriella Ferreira Ribeiro","André Martinez Ribeiro","Eduardo Lordão Oliveira","Kamylla Machado Rezende","Miguel Pereira Borges"]},{"id":"D6-10","data":"06/11/2026","dia":"Sexta-feira","ini":"16:30","fim":"19:00","atividade":"Atividade de integração (xadrez humano, caminhada, esportes) + água e barra de cereal","local":"Parque do Sabiá","vagas":29,"escalados":29,"monitores":["Adalberto Caldeira Brant Filho","Alexandre Guersoni Dias Resende","Ana Gabriella Ferreira Ribeiro","André Martinez Ribeiro","Davi Mota Campos","Débora Cristina Pereira Marra","Gustavo Martinez Ribeiro","Iara Castro Couto","isabela amorim de paula","Isabela Cunha Silva","Istéfane de souza","Jhon Waine Mendes Gonçalves (chega 17:00)","João Pedro Cardoso de Oliveira","João Pedro de Oliveira Gomes","Júlia Marques Santos","Kamylla Machado Rezende","Leandro Henrique Silva Rabelo","Letícia Moura Lemos (chega 17:00)","Maria Cecília Rodrigues Oliveira Rosa (chega 16:00)","Matheus Cardoso Miranda","Matheus Gualter Silva Resende","Melissa Oliveira Nobre","Miguel Pereira Borges","Pedro Henrique Vieira Pinto","Raul Gustavo Cavalcante Maia","Rebecca da Silva Souza","Samuel Victor Alventino Silva","Vinícius Albino Torres Lima","Vitória Gabrielly Souza Vieira (chega 17:00)"]},{"id":"D6-11","data":"06/11/2026","dia":"Sexta-feira","ini":"19:00","fim":"22:00","atividade":"Apoio Jantar e atividades com patrocinadores","local":"Arena Sabiazinho","vagas":10,"escalados":10,"monitores":["Adalberto Caldeira Brant Filho","Diogo Ricarte Loureiro Menezes","Eduardo Lordão Oliveira","Júlia Marques Santos","Leandro Henrique Silva Rabelo","Melissa Oliveira Nobre","Nicolly Ribeiro Luz","Pedro Henrique Vieira Pinto","Rhuan Henrique De Oliveira Ramos","vitor eduardo gonçalves vasconcelos"]},{"id":"D6-12","data":"06/11/2026","dia":"Sexta-feira","ini":"22:00","fim":"23:30","atividade":"Apoio Deslocamentos – embarque de volta (G1 22h, G2 23h)","local":"Estádio Parque do Sabiá – Portão 06","vagas":3,"escalados":3,"monitores":["Eduardo Lordão Oliveira","Gustavo Martinez Ribeiro","Rogério Anastácio"]},{"id":"D7-01","data":"07/11/2026","dia":"Sábado","ini":"08:00","fim":"10:00","atividade":"Apoio Café da manhã (Grupo 1 08h, Grupo 2 09h)","local":"Hotel Porto Minas – Restaurante","vagas":6,"escalados":6,"monitores":["Adalberto Caldeira Brant Filho","Alexandre Guersoni Dias Resende","Ana Gabriella Ferreira Ribeiro","Istéfane de souza","Letícia Moura Lemos","Matheus Cardoso Miranda"]},{"id":"D7-02","data":"07/11/2026","dia":"Sábado","ini":"09:00","fim":"10:30","atividade":"Apoio Deslocamentos – embarque (G1 09h, G2 10h)","local":"Hotel Porto Minas – Rua lateral","vagas":5,"escalados":5,"monitores":["André Martinez Ribeiro","Anna jullia Dos Santos Arêas","Davi Mota Campos","Débora Cristina Pereira Marra","isabela amorim de paula"]},{"id":"D7-03","data":"07/11/2026","dia":"Sábado","ini":"08:00","fim":"11:30","atividade":"Preparação da Arena para a final (balões, materiais, sinalização)","local":"Arena Sabiazinho","vagas":20,"escalados":20,"monitores":["Ana Clara Serato Rossi De Rezende","Enzo Santos Fernandes","Fred Ferreira Castro","Gustavo Martinez Ribeiro","Iara Castro Couto","Isabela Cunha Silva","Jhon Waine Mendes Gonçalves","João Gabriel Santos Nunes","Júlia Marques Santos","Kamylla Machado Rezende","Karyna Silva Leite","Laura Prado Correia","Leandro Henrique Silva Rabelo","Lethicia Ferreira de Almeida","Luciana Ferreira dos Santos","Luisa Egert Teixeira","Mariana Pinheiro Zanon","Nicolas Honorato Lima","Rayssa Pereira da Silva","Rogério Anastácio"]},{"id":"D7-04","data":"07/11/2026","dia":"Sábado","ini":"11:30","fim":"13:30","atividade":"Apoio Almoço – Praça de Alimentação","local":"Estádio Parque do Sabiá – Portão 06","vagas":16,"escalados":16,"monitores":["Diogo Ricarte Loureiro Menezes","João Pedro de Oliveira Gomes","Karolyne Cardoso Magalhães","Maria Cecília Rodrigues Oliveira Rosa","Matheus Gualter Silva Resende","Melissa Oliveira Nobre","Nicolly Ribeiro Luz","Pedro Henrique Vieira Pinto","Raul Gustavo Cavalcante Maia","Rebecca da Silva Souza","Rhuan Henrique De Oliveira Ramos","Samuel Victor Alventino Silva","Victor da Costa Mota","Vinícius Albino Torres Lima","vitor eduardo gonçalves vasconcelos","Vitória Gabrielly Souza Vieira"]},{"id":"D7-05","data":"07/11/2026","dia":"Sábado","ini":"14:00","fim":"19:00","atividade":"Final – kit alimentação e bufê de bebidas","local":"Arena Sabiazinho","vagas":5,"escalados":5,"monitores":["Débora Cristina Pereira Marra","Luisa Egert Teixeira","Miguel Pereira Borges","Rebecca da Silva Souza","Vinícius Albino Torres Lima"]},{"id":"D7-06","data":"07/11/2026","dia":"Sábado","ini":"14:00","fim":"19:00","atividade":"Final – competição principal (entrega de balões e demais atividades)","local":"Arena Sabiazinho","vagas":43,"escalados":43,"monitores":["Adalberto Caldeira Brant Filho","Alexandre Guersoni Dias Resende","Ana Clara Serato Rossi De Rezende","Ana Gabriella Ferreira Ribeiro","André Martinez Ribeiro","Anna jullia Dos Santos Arêas","Clara Magalhães dos Santos","Davi Mota Campos","Diogo Ricarte Loureiro Menezes","Enzo Santos Fernandes","Fred Ferreira Castro","Gustavo Martinez Ribeiro","Iara Castro Couto","isabela amorim de paula","Isabela Cunha Silva","Istéfane de souza","Jhon Waine Mendes Gonçalves","João Gabriel Santos Nunes","João Pedro Cardoso de Oliveira","João Pedro de Oliveira Gomes","Júlia Marques Santos","Kamylla Machado Rezende","Karolyne Cardoso Magalhães","Karyna Silva Leite","Laura Prado Correia","Leandro Henrique Silva Rabelo","Lethicia Ferreira de Almeida","Letícia Moura Lemos","Luciana Ferreira dos Santos","Maria Cecília Rodrigues Oliveira Rosa","Mariana Pinheiro Zanon","Matheus Cardoso Miranda","Matheus Gualter Silva Resende","Melissa Oliveira Nobre","Nicolas Honorato Lima","Nicolly Ribeiro Luz","Pedro Henrique Vieira Pinto","Raul Gustavo Cavalcante Maia","Rhuan Henrique De Oliveira Ramos","Samuel Victor Alventino Silva","Victor da Costa Mota","vitor eduardo gonçalves vasconcelos","Vitória Gabrielly Souza Vieira"]},{"id":"D7-07","data":"07/11/2026","dia":"Sábado","ini":"19:30","fim":"23:30","atividade":"Apoio Jantar de encerramento","local":"Arena Sabiazinho","vagas":14,"escalados":14,"monitores":["Ana Gabriella Ferreira Ribeiro","André Martinez Ribeiro","Anna jullia Dos Santos Arêas","Clara Magalhães dos Santos","Enzo Santos Fernandes","Jhon Waine Mendes Gonçalves","João Gabriel Santos Nunes","Kamylla Machado Rezende","Laura Prado Correia","Luciana Ferreira dos Santos","Luisa Egert Teixeira","Maria Cecília Rodrigues Oliveira Rosa","Raul Gustavo Cavalcante Maia","Victor da Costa Mota"]},{"id":"D7-08","data":"07/11/2026","dia":"Sábado","ini":"23:30","fim":"01:00","atividade":"Apoio Deslocamentos – embarque de volta (G1 23h30, G2 00h30)","local":"Estádio Parque do Sabiá – Portão 06","vagas":3,"escalados":3,"monitores":["Gustavo Martinez Ribeiro","Isabela Cunha Silva","Samuel Victor Alventino Silva"]}],"cronograma":[{"data":"05/11/2026","dia":"Quinta-feira","horario":"09:00–12:00","horario_melancias":"07:00 - 22:00","atividade":"Recepção dos participantes, credenciamento, fotos dos times e entrega de materiais","local":"Hotel Porto Minas – Sala 05 (305 m²)","melancias":""},{"data":"05/11/2026","dia":"Quinta-feira","horario":"14:00–17:00","horario_melancias":"13:00 - 17:00","atividade":"Apoio BTG","local":"Hotel Porto Minas – Sala 05 (305 m²)","melancias":""},{"data":"05/11/2026","dia":"Quinta-feira","horario":"18:00–19:00","horario_melancias":"16:30 - 19:00","atividade":"Apoio Meninas da Computação","local":"Hotel Porto Minas – Sala 01 (61 m²)","melancias":""},{"data":"05/11/2026","dia":"Quinta-feira","horario":"19:00–22:00","horario_melancias":"18:30 - 22:00","atividade":"Apoio Jantar de Boas-Vindas","local":"Hotel Porto Minas – Sala 05 (305 m²)","melancias":""},{"data":"06/11/2026","dia":"Sexta-feira","horario":"06:00–07:00","horario_melancias":"05:30 - 08:00","atividade":"Apoio Cafés da manhã","local":"Hotel Porto Minas – Restaurante","melancias":""},{"data":"06/11/2026","dia":"Sexta-feira","horario":"07:00–07:30","horario_melancias":"07:00 - 08:30","atividade":"Apoio Deslocamentos","local":"Hotel Porto Minas – Rua lateral","melancias":""},{"data":"06/11/2026","dia":"Sexta-feira","horario":"07:30–09:00","horario_melancias":"07:00 - 15:00","atividade":"Credenciamento tardio dos times e entrega de materiais","local":"Arena Sabiazinho","melancias":""},{"data":"06/11/2026","dia":"Sexta-feira","horario":"09:00–11:30","horario_melancias":"08:00 - 11:30\n12:00 - 13:30","atividade":"Apoio organização das palestras - integração com patrocinadores","local":"Arquibancada Arena Sabiazinho","melancias":""},{"data":"06/11/2026","dia":"Sexta-feira","horario":"11:30–13:00","horario_melancias":"11:00 - 13:00","atividade":"Apoio Almoço","local":"Estádio Parque do Sabiá – Portão 06","melancias":""},{"data":"06/11/2026","dia":"Sexta-feira","horario":"13:30–14:00","horario_melancias":"12:00 - 16:30","atividade":"Aquecimento (Warm-up) e apoio fotos oficiais","local":"Arena Sabiazinho","melancias":""},{"data":"06/11/2026","dia":"Sexta-feira","horario":"16:30–19:00","horario_melancias":"15:30 - 19:00","atividade":"Atividade de integração – Xadrez humano, caminhada, atividades esportivas diversas, inclusive com participação dos patrocinadores","local":"Parque do Sabiá","melancias":"Adalberto Caldeira Brant Filho\nAlexandre Guersoni Dias Resende\nAna Gabriella Ferreira Ribeiro\nAndré Martinez Ribeiro\nDavi Mota Campos\nDébora Cristina Pereira Marra\nGustavo Martinez Ribeiro\nIara Castro Couto\nIsabela Cunha Silva\nisabela amorim de Paula\nIstéfane de souza\nJoão Pedro Cardoso de Oliveira\nJoão Pedro de Oliveira Gomes\nJúlia Marques Santos\nKamylla Machado Rezende\nLeandro Henrique Silva Rabelo\nMatheus Cardoso Miranda\nMatheus Gualter\nmelissa nobre\nMiguel Pereira Borges\nPedro Henrique Vieira Pinto\nRaul Gustavo Cavalcante Maia\nRebecca da Silva Souza\nSamuel Victor Alventino Silva\nVinícius Albino Torres Lima\nLetícia Moura Lemos - (chega 17:00)\nVitória Gabrielly Souza Vieira - (chega 17:00)\nMaria Cecília Rodrigues Oliveira Rosa - (chega 16:00)\nJhon Waine Mendes Gonçalves - (chega 17:00)"},{"data":"06/11/2026","dia":"Sexta-feira","horario":"19:30–22:00","horario_melancias":"19:00 - 22:00","atividade":"Apoio jantar","local":"Arena Sabiazinho","melancias":""},{"data":"07/11/2026","dia":"Sábado","horario":"14:00–19:00","horario_melancias":"08:00 - 23:30","atividade":"Final da Maratona SBC de Programação","local":"Arena Sabiazinho/Estádio Parque do Sabiá – Portão 06","melancias":""}]}'''  # noqa: E501


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(str(value).replace(",", ".").strip())
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(round(_as_float(value, default)))
    except (TypeError, ValueError):
        return default


def _clean(value: Any) -> str:
    return str(value or "").strip()


def normalize_dataset(data: Mapping[str, Any] | None) -> dict[str, list[dict[str, Any]]]:
    """Deixa o dataset previsível: sem nomes vazios, números de verdade, ordenado.

    Nunca levanta exceção: se algo vier torto, o campo é corrigido ou descartado.
    Isso é o que impede a aplicação de quebrar quando a planilha muda.
    """
    data = data or {}
    monitores: list[dict[str, Any]] = []
    vistos: set[str] = set()
    for raw in data.get("monitores") or []:
        if not isinstance(raw, Mapping):
            continue
        nome = _clean(raw.get("nome"))
        if not nome or nome.lower() in vistos:
            continue
        vistos.add(nome.lower())
        dias = []
        for d in raw.get("dias") or []:
            if not isinstance(d, Mapping):
                continue
            itens = []
            for item in d.get("itens") or []:
                if not isinstance(item, Mapping):
                    continue
                atividade = _clean(item.get("atividade"))
                if not atividade:
                    continue
                itens.append(
                    {
                        "ini": _clean(item.get("ini")),
                        "fim": _clean(item.get("fim")),
                        "atividade": atividade,
                    }
                )
            dias.append({"dia": _clean(d.get("dia")), "itens": sort_day_items(itens)})
        monitores.append(
            {
                "nome": nome,
                "lista": _clean(raw.get("lista")) or "Sem lista",
                "reuniao": bool(raw.get("reuniao")),
                "horas": round(_as_float(raw.get("horas")), 1),
                "funcoes": _as_int(raw.get("funcoes")),
                "dias": dias,
            }
        )

    atividades: list[dict[str, Any]] = []
    for raw in data.get("atividades") or []:
        if not isinstance(raw, Mapping):
            continue
        atividade = _clean(raw.get("atividade"))
        if not atividade:
            continue
        atividades.append(
            {
                "id": _clean(raw.get("id")),
                "data": _clean(raw.get("data")),
                "dia": _clean(raw.get("dia")),
                "ini": _clean(raw.get("ini")),
                "fim": _clean(raw.get("fim")),
                "atividade": atividade,
                "local": _clean(raw.get("local")),
                "vagas": _as_int(raw.get("vagas")),
                "escalados": _as_int(raw.get("escalados")),
                "monitores": [_clean(p) for p in (raw.get("monitores") or []) if _clean(p)],
            }
        )

    cronograma: list[dict[str, Any]] = []
    for raw in data.get("cronograma") or []:
        if not isinstance(raw, Mapping):
            continue
        atividade = _clean(raw.get("atividade"))
        if not atividade:
            continue
        cronograma.append(
            {
                "data": _clean(raw.get("data")),
                "dia": _clean(raw.get("dia")),
                "horario": _clean(raw.get("horario")),
                "horario_melancias": _clean(raw.get("horario_melancias")),
                "atividade": atividade,
                "local": _clean(raw.get("local")),
                "melancias": _clean(raw.get("melancias")),
            }
        )

    for monitor in monitores:
        monitor["dias"].sort(key=lambda d: day_order(d.get("dia", "")))
    monitores.sort(key=lambda m: strip_accents(m["nome"]).lower())
    return {"monitores": monitores, "atividades": atividades, "cronograma": cronograma}


_DIA_CHAVES = (
    ("segunda", 0),
    ("terca", 1),
    ("quarta", 2),
    ("quinta", 3),
    ("sexta", 4),
    ("sabado", 5),
    ("domingo", 6),
)


def day_order(label: str) -> int:
    """Ordena rótulos de dia ('Quinta-feira', 'Dia 5 (qui)', ...) na semana."""
    low = strip_accents(_clean(label)).lower()
    for chave, indice in _DIA_CHAVES:
        if chave in low:
            return indice
    match = re.search(r"dia\s*(\d+)", low)
    if match:
        return int(match.group(1))
    return 99


def sort_day_items(itens: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Itens do dia em ordem de horário; sem horário vai para o fim."""
    return sorted(
        itens,
        key=lambda item: (
            parse_hhmm(item.get("ini", "")) is None,
            parse_hhmm(item.get("ini", "")) or 0,
        ),
    )


def strip_accents(text: str) -> str:
    """Remove acentos, para busca e ordenação ('Leticia' acha 'Letícia')."""
    decomposed = unicodedata.normalize("NFKD", str(text))
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def search_people(monitores: Sequence[Mapping[str, Any]], query: str) -> list[Mapping[str, Any]]:
    """Busca tolerante: ignora acento, caixa e espaços extras."""
    needle = strip_accents(_clean(query)).lower()
    if not needle:
        return list(monitores)
    return [
        m for m in monitores if needle in strip_accents(str(m.get("nome", ""))).lower()
    ]


def parse_hhmm(value: str) -> int | None:
    """'07:30' -> 450 (minutos). Devolve None se não der para ler."""
    match = re.match(r"^\s*(\d{1,2})\s*[:hH]\s*(\d{2})", str(value or ""))
    if not match:
        return None
    hours, minutes = int(match.group(1)), int(match.group(2))
    if hours > 23 or minutes > 59:
        return None
    return hours * 60 + minutes


def format_minutes(minutes: int) -> str:
    minutes = max(0, int(minutes))
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def rank_people(
    monitores: Sequence[Mapping[str, Any]],
    key: str = "horas",
    top: int | None = None,
) -> list[Mapping[str, Any]]:
    """Ranking estável: horas desc, funções desc, nome asc."""
    ordenado = sorted(
        monitores,
        key=lambda m: (
            -_as_float(m.get(key), 0.0),
            -_as_int(m.get("funcoes"), 0),
            strip_accents(str(m.get("nome", ""))).lower(),
        ),
    )
    return ordenado[:top] if top else ordenado


def total_hours(monitores: Sequence[Mapping[str, Any]]) -> float:
    return round(sum(_as_float(m.get("horas"), 0.0) for m in monitores), 1)


def assignment_datetime(day_index: int, hhmm: str) -> datetime | None:
    """Converte (dia 0/1/2, 'HH:MM') no datetime real do evento (UTC-3 fixo)."""
    minutes = parse_hhmm(hhmm)
    if minutes is None or not 0 <= day_index < len(EVENT_DAYS):
        return None
    base = datetime.combine(EVENT_DAYS[day_index], datetime.min.time())
    return base.replace(tzinfo=timezone(timedelta(hours=-3))) + timedelta(minutes=minutes)


def monitor_assignments(monitor: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Lista plana e cronológica das tarefas de uma pessoa."""
    out: list[dict[str, Any]] = []
    for day_index, dia in enumerate(monitor.get("dias") or []):
        for item in dia.get("itens") or []:
            start = assignment_datetime(day_index, item.get("ini", ""))
            end = assignment_datetime(day_index, item.get("fim", ""))
            if start and end and end <= start:
                end += timedelta(days=1)  # vira a madrugada (ex.: 23:30 -> 01:00)
            out.append(
                {
                    "dia": dia.get("dia") or "",
                    "data": EVENT_DAYS[day_index].strftime("%d/%m/%Y")
                    if day_index < len(EVENT_DAYS)
                    else "",
                    "ini": item.get("ini", ""),
                    "fim": item.get("fim", ""),
                    "atividade": item.get("atividade", ""),
                    "inicio": start,
                    "fim_dt": end,
                }
            )
    out.sort(key=lambda a: (a["inicio"] or datetime.max.replace(tzinfo=timezone.utc)))
    return out


def monitor_task_keys(monitor: Mapping[str, Any]) -> list[str]:
    """Chaves estáveis das tarefas de uma pessoa (para marcar 'feito')."""
    keys = []
    for dia in monitor.get("dias") or []:
        for item in dia.get("itens") or []:
            keys.append(f"{dia.get('dia')}|{item.get('ini')}|{item.get('atividade')}")
    return keys


def next_assignment(
    monitor: Mapping[str, Any], reference: datetime | None = None
) -> dict[str, Any] | None:
    """Próxima tarefa da pessoa a partir de `reference` (default: agora)."""
    ref = reference or datetime.now(timezone(timedelta(hours=-3)))
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone(timedelta(hours=-3)))
    for assignment in monitor_assignments(monitor):
        fim = assignment.get("fim_dt")
        if fim and fim >= ref:
            return assignment
    return None


def hours_by_day(monitor: Mapping[str, Any]) -> list[tuple[str, float]]:
    """Horas por dia, somando os intervalos da escala."""
    out: list[tuple[str, float]] = []
    for dia in monitor.get("dias") or []:
        total = 0
        for item in dia.get("itens") or []:
            start = parse_hhmm(item.get("ini", ""))
            end = parse_hhmm(item.get("fim", ""))
            if start is None or end is None:
                continue
            if end < start:
                end += 24 * 60
            total += max(0, end - start)
        out.append((str(dia.get("dia") or ""), round(total / 60, 1)))
    return out


def dataset_from_allocations_csv(text: str) -> dict[str, list[dict[str, Any]]]:
    """Monta o dataset a partir do CSV da aba "Alocações" do Google Sheets.

    Aceita o export público (`.../export?format=csv&gid=...`). Se o CSV vier
    vazio ou com cabeçalho inesperado, devolve um dataset vazio e o app usa o
    snapshot embutido — de novo: nada de tela branca.
    """
    if not text or not text.strip():
        return {"monitores": [], "atividades": [], "cronograma": []}

    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows:
        return {"monitores": [], "atividades": [], "cronograma": []}

    def pick(row: Mapping[str, Any], *names: str) -> str:
        for name in names:
            for key in row:
                if key and strip_accents(key).strip().lower() == strip_accents(name).lower():
                    return _clean(row[key])
        return ""

    atividades: dict[str, dict[str, Any]] = {}
    por_pessoa: dict[str, dict[str, Any]] = {}
    for row in rows:
        nome = pick(row, "Nome")
        atividade = pick(row, "Atividade")
        if not nome or not atividade:
            continue
        data_txt = pick(row, "Data")
        dia_txt = _weekday_pt(data_txt)
        ini, fim = pick(row, "Início", "Inicio"), pick(row, "Fim")
        horas = _as_float(pick(row, "Horas"), 0.0)
        aid = pick(row, "ID atividade", "ID") or f"{data_txt}-{atividade[:12]}"

        act = atividades.setdefault(
            aid,
            {
                "id": aid,
                "data": data_txt,
                "dia": dia_txt,
                "ini": ini,
                "fim": fim,
                "atividade": atividade,
                "local": pick(row, "Local"),
                "vagas": 0,
                "escalados": 0,
                "monitores": [],
            },
        )
        if nome not in act["monitores"]:
            act["monitores"].append(nome)
        act["escalados"] = len(act["monitores"])
        act["vagas"] = max(act["vagas"], act["escalados"])

        pessoa = por_pessoa.setdefault(
            nome.lower(),
            {
                "nome": nome,
                "lista": "Escala",
                "reuniao": False,
                "horas": 0.0,
                "funcoes": 0,
                "dias": {},
            },
        )
        pessoa["horas"] = round(_as_float(pessoa["horas"]) + horas, 1)
        pessoa["funcoes"] = _as_int(pessoa["funcoes"]) + 1
        dia_key = _weekday_pt(data_txt)
        bucket = pessoa["dias"].setdefault(dia_key, {"dia": dia_key, "itens": []})
        bucket["itens"].append({"ini": ini, "fim": fim, "atividade": atividade})

    monitores = []
    for pessoa in por_pessoa.values():
        dias = [pessoa["dias"][k] for k in sorted(pessoa["dias"])]
        pessoa["dias"] = dias
        monitores.append(pessoa)

    return normalize_dataset(
        {
            "monitores": monitores,
            "atividades": list(atividades.values()),
            "cronograma": [],
        }
    )


_WEEKDAYS_PT = {
    0: "Segunda-feira",
    1: "Terça-feira",
    2: "Quarta-feira",
    3: "Quinta-feira",
    4: "Sexta-feira",
    5: "Sábado",
    6: "Domingo",
}


def _weekday_pt(value: str) -> str:
    """Aceita 05/11/2026, 2026-11-05 ou serial do Excel e devolve o dia da semana."""
    raw = _clean(value)
    if not raw:
        return ""
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return _WEEKDAYS_PT[datetime.strptime(raw, fmt).weekday()]
        except ValueError:
            continue
    if re.fullmatch(r"\d+(\.\d+)?", raw):  # serial do Excel
        try:
            return _WEEKDAYS_PT[(date(1899, 12, 30) + timedelta(days=int(float(raw)))).weekday()]
        except (ValueError, OverflowError):
            return ""
    return raw


# ---------------------------------------------------------------------------
# Funil: o caminho que a pessoa fez e o caminho "correto"
# ---------------------------------------------------------------------------


def dedupe_consecutive(items: Iterable[str]) -> list[str]:
    out: list[str] = []
    for item in items:
        if not out or out[-1] != item:
            out.append(item)
    return out


def analyze_path(
    visited: Sequence[str], canonical: Sequence[str] = CANONICAL_STEPS
) -> dict[str, Any]:
    """Compara a navegação real com o caminho esperado.

    Devolve:
      sequencia     -> telas na ordem em que foram abertas (sem repetição seguida)
      faltando      -> telas do caminho que a pessoa não abriu
      fora_de_ordem -> True se voltou/avançou fora da ordem canônica
      primeira_falha-> primeira tela pulada com alguma tela posterior visitada
      completude    -> 0..1 (quantas telas do caminho foram vistas)
      status        -> "completo" | "parcial" | "incompleto"
      parou_em      -> última tela aberta (para medir abandono)
    """
    canonical = tuple(canonical)
    valid = set(canonical)
    sequencia = dedupe_consecutive([s for s in visited if s in valid])
    vistas = set(sequencia)
    faltando = [s for s in canonical if s not in vistas]

    posicoes = [canonical.index(s) for s in sequencia]
    fora_de_ordem = any(
        depois < antes for antes, depois in zip(posicoes, posicoes[1:], strict=False)
    )

    primeira_falha = None
    for index, step in enumerate(canonical):
        if step in vistas:
            continue
        posteriores = set(canonical[index + 1 :])
        if vistas & posteriores:
            primeira_falha = step
        break

    completude = len(vistas) / len(canonical) if canonical else 0.0
    if completude >= 1.0:
        status = "completo"
    elif completude > 0:
        status = "parcial"
    else:
        status = "incompleto"

    return {
        "sequencia": sequencia,
        "faltando": faltando,
        "fora_de_ordem": fora_de_ordem,
        "primeira_falha": primeira_falha,
        "completude": round(completude, 3),
        "status": status,
        "parou_em": sequencia[-1] if sequencia else "",
    }


def path_badges(sequencia: Sequence[str]) -> str:
    """Trilha bonitinha para o painel: 🍉 → 🙋 → 📋 ..."""
    if not sequencia:
        return "—"
    return " → ".join(f"{SCREENS.get(s, ('❓', s))[0]}" for s in sequencia)


def path_label(sequencia: Sequence[str]) -> str:
    if not sequencia:
        return "—"
    return " → ".join(SCREENS.get(s, ("❓", s))[1] for s in sequencia)


# ---------------------------------------------------------------------------
# Geolocalização / VPN: só país, nunca IP
# ---------------------------------------------------------------------------

COUNTRY_HEADERS = (
    "cf-ipcountry",
    "x-vercel-ip-country",
    "x-country-code",
    "x-geo-country",
    "x-appengine-country",
    "x-azure-country",
)

IP_HEADERS = ("cf-connecting-ip", "true-client-ip", "x-real-ip", "x-forwarded-for")


def header_value(headers: Mapping[str, Any] | None, name: str) -> str:
    """Busca cabeçalho sem depender de caixa (dict ou Headers do Streamlit)."""
    if not headers:
        return ""
    try:
        for key, value in headers.items():
            if str(key).strip().lower() == name.lower():
                return _clean(value)
    except Exception:  # pragma: no cover - cabeçalhos exóticos
        return ""
    return ""


def client_ip(headers: Mapping[str, Any] | None) -> str:
    """Primeiro IP público da cadeia de proxies ('' se não houver)."""
    for name in IP_HEADERS:
        raw = header_value(headers, name)
        if not raw:
            continue
        for part in raw.split(","):
            candidate = part.strip()
            if candidate:
                return candidate
    return ""


def is_public_ip(ip: str) -> bool:
    import ipaddress

    try:
        addr = ipaddress.ip_address(str(ip).strip())
    except ValueError:
        return False
    return not (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_reserved
        or addr.is_unspecified
    )


def detect_country(
    headers: Mapping[str, Any] | None,
    ip: str = "",
    lookup: Callable[[str], str] | None = None,
) -> tuple[str, str]:
    """Devolve (código do país, de onde veio a informação).

    Ordem: cabeçalho do CDN -> lookup opcional (se configurado) -> desconhecido.
    """
    for name in COUNTRY_HEADERS:
        value = header_value(headers, name).upper()
        if value == "T1":  # Cloudflare marca saída de rede Tor assim
            return "T1", f"header:{name}"
        if value == "XX":  # Cloudflare não soube dizer
            return "??", f"header:{name}"
        if re.fullmatch(r"[A-Z]{2}", value):
            return value, f"header:{name}"

    ip = ip or client_ip(headers)
    if ip and is_public_ip(ip) and lookup:
        try:
            value = _clean(lookup(ip)).upper()
        except Exception:
            value = ""
        if re.fullmatch(r"[A-Z]{2}", value):
            return value, "lookup"

    if ip and not is_public_ip(ip):
        return "LOCAL", "ip-privado"
    return "??", "desconhecido"


def geo_decision(country: str, cfg: Settings) -> tuple[bool, str]:
    """Decide se libera o acesso. Retorna (liberado, motivo)."""
    if cfg.geo_mode == "off":
        return True, "geo desligado"
    country = (country or "??").upper()
    if country in {"LOCAL", "??", ""}:
        if cfg.unknown_country_policy == "allow":
            return True, "país não identificado (modo tolerante)"
        return False, "país não identificado"
    if country in cfg.allowed_countries:
        return True, f"país permitido: {country}"
    if country == "T1":
        return False, "saída de rede Tor"
    return False, f"país fora da lista: {country}"


def lookup_country_http(url_template: str, timeout: float = 2.0) -> Callable[[str], str]:
    """Cria um lookup de país via HTTP (opt-in, com timeout curto)."""

    def _lookup(ip: str) -> str:
        import urllib.request

        url = url_template.replace("{ip}", ip)
        req = urllib.request.Request(url, headers={"User-Agent": "melancias/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.read(8).decode("utf-8", "ignore").strip()

    return _lookup


def ip_intel(ip: str, url_template: str, timeout: float = 1.5) -> dict[str, Any]:
    """Consulta opcional de reputação do IP (proxy/hosting).

    É best-effort: erro, timeout ou resposta estranha => dicionário vazio.
    """
    if not ip or not url_template:
        return {}
    try:
        import urllib.request

        url = url_template.replace("{ip}", ip)
        req = urllib.request.Request(url, headers={"User-Agent": "melancias/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as response:
            payload = json.loads(response.read(4096).decode("utf-8", "ignore"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def assess_access(
    headers: Mapping[str, Any] | None,
    cfg: Settings,
    lookup: Callable[[str], str] | None = None,
    intel: Callable[[str, str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Junta país + reputação de IP numa decisão única e explicável."""
    ip = client_ip(headers)
    country, source = detect_country(headers, ip=ip, lookup=lookup)
    allowed, reason = geo_decision(country, cfg)
    info: dict[str, Any] = {}

    if cfg.ip_intel and ip:
        info = (intel or ip_intel)(ip, cfg.ip_intel_url)
        if info.get("status") == "success":
            detected = _clean(info.get("countryCode")).upper()
            if detected and country in {"??", "LOCAL"}:
                country, source = detected, "ip-intel"
                allowed, reason = geo_decision(country, cfg)
            if allowed and (info.get("proxy") or info.get("hosting")):
                allowed = False
                reason = "VPN/proxy ou hospedagem de datacenter"
    return {
        "ip_presente": bool(ip),
        "pais": country,
        "origem_pais": source,
        "liberado": allowed,
        "motivo": reason,
        "intel": info,
    }


# ---------------------------------------------------------------------------
# Sessão anônima: cookie first-party + query param de recuperação
# ---------------------------------------------------------------------------

SID_RE = re.compile(r"^[0-9a-f]{32}$")

COOKIE_JS = """
<script>
(function () {
  try {
    var name = "__COOKIE_NAME__";
    var days = __COOKIE_DAYS__;
    var sid = "__SID__";
    var parent = window.parent;
    var url = new URL(parent.location.href);
    var current = url.searchParams.get("s");
    function readCookie(n) {
      var m = document.cookie.match(new RegExp("(?:^|; )" + n + "=([^;]*)"));
      return m ? decodeURIComponent(m[1]) : null;
    }
    function writeCookie(n, v, d) {
      var exp = new Date(Date.now() + d * 864e5).toUTCString();
      document.cookie = n + "=" + encodeURIComponent(v) +
        "; expires=" + exp + "; path=/; SameSite=Lax";
    }
    var stored = readCookie(name);
    if (current) {
      if (stored !== current) { writeCookie(name, current, days); }
      return;
    }
    if (stored) {
      var guard = "melancias_restore_" + stored;
      if (!parent.sessionStorage.getItem(guard)) {
        parent.sessionStorage.setItem(guard, "1");
        url.searchParams.set("s", stored);
        parent.location.replace(url.toString());
      }
      return;
    }
    writeCookie(name, sid, days);
  } catch (e) { /* cookie bloqueado: segue só com a sessão */ }
})();
</script>
"""


def new_sid() -> str:
    return uuid.uuid4().hex


def query_param_sid() -> str:
    """Lê ?s=... quando existir (recuperação de sessão via cookie)."""
    try:
        value = _clean(st.query_params.get("s", ""))
    except Exception:
        return ""
    return value if SID_RE.match(value) else ""


_HTML_JS_SUPPORT: bool | None = None


def supports_html_js() -> bool:
    """Streamlit >= 1.66 executa JS via st.html; antes disso, só via iframe."""
    global _HTML_JS_SUPPORT
    if _HTML_JS_SUPPORT is None:
        try:
            _HTML_JS_SUPPORT = "unsafe_allow_javascript" in inspect.signature(st.html).parameters
        except Exception:
            _HTML_JS_SUPPORT = False
    return _HTML_JS_SUPPORT


def run_js(script: str) -> None:
    """Roda um script mínimo (cookie). Se nada funcionar, o app segue vivo."""
    try:
        if supports_html_js():
            st.html(f"<script>{script}</script>", unsafe_allow_javascript=True)
            return
    except Exception:
        pass
    try:
        components.html(f"<script>{script}</script>", height=0, scrolling=False)
    except Exception:
        pass


def cookie_bridge(cfg: Settings, sid: str) -> None:
    """Sincroniza o cookie first-party com o id da sessão (falha em silêncio)."""
    script = (
        COOKIE_JS.replace("__COOKIE_NAME__", cfg.cookie_name)
        .replace("__COOKIE_DAYS__", str(max(1, cfg.cookie_days)))
        .replace("__SID__", sid)
    )
    run_js(script)


def pixel_markup(cfg: Settings, sid: str, screen: str) -> str:
    """Pixel 1x1 opcional: só existe se ANALYTICS_PIXEL_URL estiver configurado."""
    if not cfg.pixel_url:
        return ""
    params = urlencode(
        {"e": "view", "s": sid, "p": screen, "t": int(time.time() * 1000)}
    )
    separator = "&" if "?" in cfg.pixel_url else "?"
    url = html.escape(f"{cfg.pixel_url}{separator}{params}", quote=True)
    return (
        f'<img src="{url}" width="1" height="1" alt="" '
        'style="position:absolute;left:-9999px;top:-9999px" />'
    )


def render_pixel(cfg: Settings, sid: str, screen: str) -> None:
    """Insere o pixel 1x1 no DOM (sem iframe e sem JS)."""
    markup = pixel_markup(cfg, sid, screen)
    if not markup:
        return
    try:
        st.html(markup)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Armazenamento dos eventos (SQLite, opcional e tolerante a falha)
# ---------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    ts      TEXT NOT NULL,
    sid     TEXT NOT NULL,
    kind    TEXT NOT NULL,
    screen  TEXT,
    person  TEXT,
    country TEXT,
    meta    TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_sid ON events(sid);
CREATE INDEX IF NOT EXISTS idx_events_ts  ON events(ts);
"""

ALLOWED_KINDS = {
    "view",
    "leave",
    "identify",
    "consent",
    "task_done",
    "word",
    "photo",
    "pronto",
    "blocked",
    "admin",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class AnalyticsStore:
    """Log de navegação em SQLite.

    - Nunca grava IP, foto, texto de meditação ou qualquer conteúdo sensível.
    - Se o disco não for gravável (ex.: deploy read-only), cai para memória e
      a aplicação continua funcionando normalmente (`self.degraded = True`).
    """

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        self.degraded = False
        self._lock = threading.Lock()
        self._conn = self._connect()
        self._ensure_schema()

    # -- infra ------------------------------------------------------------
    def _connect(self) -> sqlite3.Connection:
        try:
            target = Path(self.path)
            if target.parent and str(target.parent) not in {"", "."}:
                target.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.path, check_same_thread=False, timeout=5)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            return conn
        except Exception:
            self.degraded = True
            conn = sqlite3.connect(":memory:", check_same_thread=False)
            conn.execute("PRAGMA journal_mode=MEMORY")
            return conn

    def _ensure_schema(self) -> None:
        with self._lock:
            try:
                self._conn.executescript(SCHEMA)
                self._conn.commit()
            except Exception:
                self.degraded = True

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass

    # -- escrita ----------------------------------------------------------
    def log(
        self,
        sid: str,
        kind: str,
        screen: str = "",
        person: str = "",
        country: str = "",
        meta: Mapping[str, Any] | None = None,
    ) -> None:
        """Grava um evento. Falha de banco nunca derruba a página."""
        if kind not in ALLOWED_KINDS:
            kind = "view"
        payload = json.dumps(dict(meta or {}), ensure_ascii=False)[:2000]
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO events (ts, sid, kind, screen, person, country, meta)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (utc_now_iso(), sid, kind, screen, person, country, payload),
                )
                self._conn.commit()
            except Exception:
                self.degraded = True

    def purge(self, retention_days: int) -> int:
        """Apaga eventos mais antigos que a retenção. Devolve quantos saíram."""
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=max(1, retention_days))
        ).isoformat(timespec="seconds")
        with self._lock:
            try:
                cur = self._conn.execute("DELETE FROM events WHERE ts < ?", (cutoff,))
                self._conn.commit()
                return int(cur.rowcount or 0)
            except Exception:
                return 0

    def delete_sid(self, sid: str) -> int:
        with self._lock:
            try:
                cur = self._conn.execute("DELETE FROM events WHERE sid = ?", (sid,))
                self._conn.commit()
                return int(cur.rowcount or 0)
            except Exception:
                return 0

    def clear_all(self) -> int:
        with self._lock:
            try:
                cur = self._conn.execute("DELETE FROM events")
                self._conn.commit()
                return int(cur.rowcount or 0)
            except Exception:
                return 0

    # -- leitura ----------------------------------------------------------
    def rows(self, limit: int = 5000) -> list[dict[str, Any]]:
        with self._lock:
            try:
                self._conn.row_factory = sqlite3.Row
                cur = self._conn.execute(
                    "SELECT id, ts, sid, kind, screen, person, country, meta FROM events"
                    " ORDER BY ts ASC, id ASC LIMIT ?",
                    (int(limit),),
                )
                return [dict(row) for row in cur.fetchall()]
            except Exception:
                return []

    def count(self) -> int:
        with self._lock:
            try:
                cur = self._conn.execute("SELECT COUNT(*) FROM events")
                return int(cur.fetchone()[0])
            except Exception:
                return 0

    def session_paths(self) -> list[dict[str, Any]]:
        """Agrupa eventos por sessão e devolve a trilha de cada uma."""
        events = self.rows()
        grouped: dict[str, list[dict[str, Any]]] = {}
        for event in events:
            grouped.setdefault(str(event.get("sid") or ""), []).append(event)

        sessions: list[dict[str, Any]] = []
        for sid, items in grouped.items():
            views = [e["screen"] for e in items if e.get("kind") == "view" and e.get("screen")]
            person = next((e["person"] for e in items if e.get("person")), "")
            country = next((e["country"] for e in items if e.get("country")), "")
            analysis = analyze_path(views)
            sessions.append(
                {
                    "sid": sid,
                    "primeiro": items[0]["ts"],
                    "ultimo": items[-1]["ts"],
                    "ultimo_id": items[-1].get("id", 0),
                    "eventos": len(items),
                    "pessoa": person,
                    "pais": country,
                    "sequencia": analysis["sequencia"],
                    "completude": analysis["completude"],
                    "status": analysis["status"],
                    "fora_de_ordem": analysis["fora_de_ordem"],
                    "primeira_falha": analysis["primeira_falha"],
                    "parou_em": analysis["parou_em"],
                    "faltando": analysis["faltando"],
                }
            )
        sessions.sort(key=lambda s: (s["ultimo"], s["ultimo_id"]), reverse=True)
        return sessions

    def screen_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for event in self.rows():
            if event.get("kind") == "view" and event.get("screen"):
                counts[event["screen"]] = counts.get(event["screen"], 0) + 1
        return counts

    def blocked(self) -> list[dict[str, Any]]:
        return [e for e in self.rows() if e.get("kind") == "blocked"]

    def to_csv(self) -> str:
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["ts", "sid", "kind", "screen", "person", "country", "meta"])
        for event in self.rows():
            writer.writerow(
                [
                    event.get("ts", ""),
                    event.get("sid", ""),
                    event.get("kind", ""),
                    event.get("screen", ""),
                    event.get("person", ""),
                    event.get("country", ""),
                    event.get("meta", ""),
                ]
            )
        return buffer.getvalue()


@st.cache_resource(show_spinner=False)
def get_store(path: str) -> AnalyticsStore:
    """Uma conexão por processo (cache_resource), com retenção aplicada."""
    return AnalyticsStore(path)


def funnel_report(sessions: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Números do funil para o painel da organização."""
    total = len(sessions)
    completos = sum(1 for s in sessions if s.get("status") == "completo")
    parciais = sum(1 for s in sessions if s.get("status") == "parcial")
    fora = sum(1 for s in sessions if s.get("fora_de_ordem"))
    identificados = sum(1 for s in sessions if s.get("pessoa"))

    por_tela: dict[str, int] = {}
    abandono: dict[str, int] = {}
    for session in sessions:
        for screen in set(session.get("sequencia") or []):
            por_tela[screen] = por_tela.get(screen, 0) + 1
        last = session.get("parou_em") or ""
        if last:
            abandono[last] = abandono.get(last, 0) + 1

    return {
        "sessoes": total,
        "identificadas": identificados,
        "completas": completos,
        "parciais": parciais,
        "fora_de_ordem": fora,
        "taxa_conclusao": round(completos / total, 3) if total else 0.0,
        "por_tela": por_tela,
        "abandono": abandono,
    }


def dwell_by_screen(
    events: Sequence[Mapping[str, Any]], cap_seconds: int = 1800
) -> dict[str, float]:
    """Tempo médio (s) entre abrir uma tela e trocar de tela.

    Ignora intervalos maiores que `cap_seconds` (aba esquecida aberta) e
    sessões sem evento de saída.
    """
    totals: dict[str, list[float]] = {}
    last: dict[str, tuple[str, str]] = {}
    for event in events:
        sid = str(event.get("sid") or "")
        kind = event.get("kind")
        screen = str(event.get("screen") or "")
        if kind == "view" and screen:
            last[sid] = (screen, str(event.get("ts") or ""))
        elif kind == "leave" and screen:
            previous = last.pop(sid, None)
            if not previous or previous[0] != screen:
                continue
            try:
                start = datetime.fromisoformat(previous[1].replace("Z", "+00:00"))
                end = datetime.fromisoformat(str(event.get("ts")).replace("Z", "+00:00"))
            except (TypeError, ValueError):
                continue
            delta = (end - start).total_seconds()
            if 0 <= delta <= cap_seconds:
                totals.setdefault(screen, []).append(delta)
    return {
        screen: round(sum(values) / len(values), 1)
        for screen, values in totals.items()
        if values
    }


# ---------------------------------------------------------------------------
# Interface: CSS, componentes e consentimento
# ---------------------------------------------------------------------------

CSS = """
<style>
  :root {
    --mela-flesh: #ff4d6d;
    --mela-deep:  #c9184a;
    --mela-rind:  #2fbf71;
    --mela-cream: #fff8f0;
    --mela-ink:   #14231c;
  }
  .stApp {
    background:
      radial-gradient(1200px 500px at 10% -10%, #ffe3e8 0%, transparent 60%),
      radial-gradient(900px 400px at 100% 0%, #e3fbf0 0%, transparent 55%),
      var(--mela-cream);
  }
  section[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #fffdfa 0%, #f4fff8 100%);
    border-right: 1px solid #f0e6dc;
  }
  h1, h2, h3 { letter-spacing: -0.02em; color: var(--mela-ink); }
  .mela-hero {
    background: linear-gradient(120deg, #ff4d6d 0%, #ff8fa3 45%, #2fbf71 130%);
    color: #fff;
    padding: 28px 30px;
    border-radius: 26px;
    box-shadow: 0 18px 40px rgba(201, 24, 74, .22);
    margin-bottom: 18px;
  }
  .mela-hero h1 { color: #fff; margin: 0 0 6px 0; font-size: 2.15rem; }
  .mela-hero p  { margin: 0; opacity: .95; font-size: 1.02rem; }
  .mela-card {
    background: #fff;
    border: 1px solid #f3e9e0;
    border-radius: 20px;
    padding: 18px 20px;
    box-shadow: 0 8px 24px rgba(20, 35, 28, .06);
    height: 100%;
  }
  .mela-card h3 { margin: 0 0 6px 0; font-size: 1.05rem; }
  .mela-card p  { margin: 0; color: #4a5a52; font-size: .95rem; }
  .mela-big { font-size: 1.9rem; font-weight: 700; color: var(--mela-deep); }
  .mela-chip {
    display: inline-block;
    background: #ffe3e8;
    color: #a4161a;
    border-radius: 999px;
    padding: 6px 14px;
    margin: 4px 6px 4px 0;
    font-size: .92rem;
    font-weight: 600;
  }
  .mela-chip.green { background: #d8fbe8; color: #146b3f; }
  .mela-chip.gold  { background: #fff3cd; color: #7a5b00; }
  .mela-stepper {
    display: flex; flex-wrap: wrap; gap: 6px; margin: 0 0 18px 0;
  }
  .mela-step {
    border-radius: 999px; padding: 6px 12px; font-size: .82rem;
    background: #f1f1f1; color: #6b6b6b; border: 1px solid #e6e6e6;
  }
  .mela-step.done { background: #d8fbe8; color: #146b3f; border-color: #b7f0d0; }
  .mela-step.now  { background: #ffe3e8; color: #a4161a; border-color: #ffc9d4; font-weight: 700; }
  .mela-podium {
    text-align: center; background: #fff; border-radius: 20px;
    padding: 16px 10px; border: 1px solid #f3e9e0;
  }
  .mela-podium .who { font-weight: 700; font-size: .95rem; margin-top: 6px; }
  .mela-podium .hrs { color: var(--mela-deep); font-weight: 800; font-size: 1.25rem; }
  .mela-note {
    background: #f4fff8; border-left: 4px solid var(--mela-rind);
    padding: 12px 16px; border-radius: 10px; color: #214b37;
  }
  .mela-alert {
    background: #fff5f7; border-left: 4px solid var(--mela-flesh);
    padding: 12px 16px; border-radius: 10px; color: #7a1a2c;
  }
  .breath {
    width: 150px; height: 150px; margin: 10px auto; border-radius: 50%;
    background: radial-gradient(circle at 35% 30%, #ff8fa3, #ff4d6d 70%);
    animation: breathe 12s ease-in-out infinite;
    box-shadow: 0 0 0 0 rgba(255, 77, 109, .35);
  }
  @keyframes breathe {
    0%, 100% { transform: scale(.78); box-shadow: 0 0 0 0 rgba(255,77,109,.25); }
    45%      { transform: scale(1.06); box-shadow: 0 0 0 26px rgba(255,77,109,0); }
    55%      { transform: scale(1.06); }
  }
  .mela-small { color: #6b7a72; font-size: .85rem; }
  footer, #MainMenu { visibility: hidden; }
</style>
"""


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def esc(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def hero(title: str, subtitle: str, emoji: str = "🍉") -> None:
    st.markdown(
        f'<div class="mela-hero"><h1>{emoji} {esc(title)}</h1>'
        f"<p>{esc(subtitle)}</p></div>",
        unsafe_allow_html=True,
    )


def card(title: str, body: str, emoji: str = "") -> None:
    st.markdown(
        f'<div class="mela-card"><h3>{emoji} {esc(title)}</h3>'
        f"<p>{body}</p></div>",
        unsafe_allow_html=True,
    )


def chip(text: str, style: str = "") -> str:
    klass = f"mela-chip {style}".strip()
    return f'<span class="{klass}">{esc(text)}</span>'


def note(text: str, alert: bool = False) -> None:
    klass = "mela-alert" if alert else "mela-note"
    st.markdown(f'<div class="{klass}">{text}</div>', unsafe_allow_html=True)


def stepper(visited: Sequence[str], current: str) -> None:
    parts = []
    for step in CANONICAL_STEPS:
        emoji, label = SCREENS[step]
        klass = "mela-step"
        if step == current:
            klass += " now"
        elif step in visited:
            klass += " done"
        parts.append(f'<span class="{klass}">{emoji} {esc(label)}</span>')
    st.markdown(f'<div class="mela-stepper">{"".join(parts)}</div>', unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Estado da sessão + consentimento
# ---------------------------------------------------------------------------


def init_state() -> None:
    ss = st.session_state
    if "sid" not in ss:
        ss.sid = query_param_sid() or new_sid()
    ss.setdefault("consent", None)  # None | "granted" | "denied"
    ss.setdefault("views", [])
    ss.setdefault("person", "")
    ss.setdefault("words", [])
    ss.setdefault("photos", [])
    ss.setdefault("checkin", None)
    ss.setdefault("tasks_done", [])
    ss.setdefault("access", None)
    ss.setdefault("screen", "inicio")
    ss.setdefault("last_logged_view", "")
    ss.setdefault("admin_ok", False)


def analytics_on(cfg: Settings) -> bool:
    """Só registra com consentimento (ou se o dono desligou a exigência)."""
    if not cfg.consent_required:
        return True
    return st.session_state.get("consent") == "granted"


def consent_banner(cfg: Settings, store: AnalyticsStore) -> None:
    """Banner honesto: diz o que é medido, para quê, e como apagar."""
    ss = st.session_state
    if not cfg.consent_required:
        note(
            "🍉 <b>Transparência:</b> esta instância registra navegação por tela "
            "(sem IP, sem foto, sem conteúdo da meditação). Detalhes em "
            "<b>Privacidade</b>.",
        )
        return
    if ss.consent is not None:
        return

    with st.container(border=True):
        st.markdown("### 🍉 Um combinado rápido antes de começar")
        st.markdown(
            "A gente quer cuidar melhor de vocês e da escala. Para isso, "
            "**se você deixar**, guardamos apenas: a tela que você abriu, a ordem "
            "do caminho, seu nome (se você escolher) e o país de acesso. "
            "**Não** guardamos IP, fotos, palavras da meditação nem gravação de tela. "
            "Você pode apagar tudo depois em **Privacidade**."
        )
        col1, col2 = st.columns(2)
        if col1.button("✅ Pode registrar", use_container_width=True, type="primary"):
            ss.consent = "granted"
            store.log(ss.sid, "consent", meta={"decision": "granted"})
            st.rerun()
        if col2.button("🙅 Só o essencial", use_container_width=True):
            ss.consent = "denied"
            st.rerun()
        st.caption(
            "Sem consentimento o app funciona igual — só não gera estatística. "
            "Base legal: consentimento (LGPD art. 7º, I)."
        )


def track(
    cfg: Settings,
    store: AnalyticsStore,
    kind: str,
    screen: str = "",
    person: str = "",
    country: str = "",
    meta: Mapping[str, Any] | None = None,
) -> None:
    """Ponto único de escrita de eventos (respeita consentimento e geo)."""
    if not analytics_on(cfg):
        return
    access = st.session_state.get("access") or {}
    if not access.get("liberado", True):
        return
    store.log(
        st.session_state.get("sid", ""),
        kind,
        screen=screen,
        person=person or st.session_state.get("person", ""),
        country=country or str(access.get("pais", "")),
        meta=meta,
    )


def enter_screen(cfg: Settings, store: AnalyticsStore, screen: str, country: str) -> None:
    """Registra troca de tela (com tempo na anterior) e dispara o pixel.

    Sem consentimento, a trilha existe só na memória do navegador (para o
    stepper continuar funcionando) e nada vai para o banco.
    """
    ss = st.session_state
    if screen not in ss.views:
        ss.views.append(screen)

    if not analytics_on(cfg):
        return

    previous = ss.get("last_logged_view") or ""
    if previous == screen:
        return
    if previous:
        track(cfg, store, "leave", screen=previous, country=country)
    ss.last_logged_view = screen
    track(cfg, store, "view", screen=screen, country=country)
    render_pixel(cfg, ss.sid, screen)


# ---------------------------------------------------------------------------
# Páginas
# ---------------------------------------------------------------------------


def go(screen: str) -> None:
    """Navegação programática sem brigar com o widget da sidebar."""
    st.session_state["goto"] = screen
    st.rerun()


def page_inicio(data: Mapping[str, Any]) -> None:
    monitores = data["monitores"]
    hero(
        "Bem-vinde, melancia!",
        f"{len(monitores)} pessoas, {total_hours(monitores):g} horas de cuidado e "
        f"uma maratona que só funciona porque você tá aqui. 🍉",
    )

    cols = st.columns(4)
    cols[0].metric("🍉 melancias", len(monitores))
    cols[1].metric("⏱️ horas somadas", f"{total_hours(monitores):g}h")
    cols[2].metric("🗓️ atividades", len(data["atividades"]))
    cols[3].metric(
        "🤝 reunião 02/11",
        f"{sum(1 for m in monitores if m['reuniao'])}/{len(monitores)}",
    )

    st.markdown("### ✨ Seu caminho em 3 toques")
    c1, c2, c3 = st.columns(3)
    with c1:
        card(
            "1. Se apresenta",
            "Escolhe seu nome na lista. A partir daí o app fala só com você.",
            "🙋",
        )
        if st.button("Quem sou eu?", key="home_quem", width="stretch"):
            go("quem")
    with c2:
        card(
            "2. Vê seu resumo",
            "Sua escala dos 3 dias, horas e a próxima tarefa — sem abrir aba nenhuma.",
            "📋",
        )
        if st.button("Abrir meu resumo", key="home_resumo", width="stretch"):
            go("resumo")
    with c3:
        card(
            "3. Respira",
            "Um cantinho pra soltar uma palavra boa e mandar foto (que não fica salva).",
            "🧘",
        )
        if st.button("Ir meditar", key="home_med", width="stretch"):
            go("meditacao")

    st.markdown("### 🍉 O que rola hoje")
    if data["cronograma"]:
        for item in data["cronograma"][:6]:
            st.markdown(
                f"**{esc(item['horario'])}** · {esc(item['atividade'])} "
                f"<span class='mela-small'>— {esc(item['local'])}</span>",
                unsafe_allow_html=True,
            )
    else:
        st.info("Cronograma não carregado — a escala completa segue em **Tarefas de todos**.")

    st.markdown("")
    note(
        "💚 <b>Cuidado é método:</b> ninguém aqui precisa dar conta de tudo. "
        "Se sua escala pesar, fala com o núcleo. A gente ajusta junto.",
    )
    st.caption(
        "Acesso liberado para redes no Brasil. Registro de navegação só com o seu ok "
        "— veja **Privacidade**."
    )


def page_quem(cfg: Settings, data: Mapping[str, Any], store: AnalyticsStore, country: str) -> None:
    hero("Quem é você?", "Acha seu nome e a gente monta seu resumo na hora.", "🙋")
    monitores = data["monitores"]
    query = st.text_input(
        "🔎 Buscar seu nome",
        placeholder="ex.: isabela, rebecca, samuel...",
        key="busca_nome",
    )
    encontrados = search_people(monitores, query)
    if not encontrados:
        st.warning("Não achei ninguém com esse nome 😅 tenta só o primeiro nome.")
        return

    nomes = [m["nome"] for m in encontrados]
    escolhido = st.selectbox(
        f"{len(nomes)} pessoa(s) encontrada(s)", nomes, key="select_nome"
    )
    if st.button("✅ Sou eu!", type="primary", width="stretch"):
        st.session_state.person = escolhido
        track(cfg, store, "identify", screen="quem", person=escolhido, country=country)
        go("resumo")

    if st.session_state.person:
        st.caption(f"Você está identificade como **{st.session_state.person}**.")
        if st.button("Trocar de pessoa", key="trocar"):
            st.session_state.person = ""
            st.rerun()

    with st.expander("Não achou seu nome? 🫂"):
        st.markdown(
            "Respira. Manda uma mensagem pro núcleo que a gente te coloca na escala "
            "e atualiza o painel. Ninguém fica de fora."
        )


def _timeline(monitor: Mapping[str, Any], tasks_done: Sequence[str]) -> None:
    for dia in monitor.get("dias") or []:
        itens = dia.get("itens") or []
        if not itens:
            continue
        st.markdown(f"#### {esc(dia.get('dia') or '')}")
        for item in itens:
            key = f"{dia.get('dia')}|{item.get('ini')}|{item.get('atividade')}"
            feito = key in tasks_done
            col1, col2 = st.columns([5, 1])
            with col1:
                prefix = "✅" if feito else "🕒"
                st.markdown(
                    f"{prefix} **{esc(item.get('ini'))}–{esc(item.get('fim'))}** · "
                    f"{esc(item.get('atividade'))}"
                )
            with col2:
                marcado = st.checkbox(
                    "feito",
                    key=f"done_{key}",
                    value=feito,
                    label_visibility="collapsed",
                )
                if marcado:
                    if key not in tasks_done:
                        tasks_done.append(key)
                elif key in tasks_done:
                    tasks_done.remove(key)


def page_resumo(
    cfg: Settings, data: Mapping[str, Any], store: AnalyticsStore, country: str
) -> None:
    nome = st.session_state.get("person") or ""
    if not nome:
        hero("Primeiro, quem é você?", "A gente precisa saber pra mostrar a SUA escala.", "🙋")
        if st.button("Escolher meu nome", type="primary"):
            go("quem")
        return

    monitor = next((m for m in data["monitores"] if m["nome"] == nome), None)
    if not monitor:
        st.warning("Achei seu nome na sessão mas não na escala atual. Fala com o núcleo 💚")
        if st.button("Escolher de novo"):
            go("quem")
        return

    hero(f"Oi, {nome.split()[0]}!", "Aqui está tudo o que é seu — sem aba, sem mistério.", "📋")

    cols = st.columns(4)
    cols[0].metric("⏱️ horas", f"{monitor['horas']:g}h")
    cols[1].metric("🧩 funções", monitor["funcoes"])
    cols[2].metric("📋 lista", monitor["lista"].replace("Núcleo (Estatísticas)", "Núcleo"))
    cols[3].metric("🤝 reunião 02/11", "sim" if monitor["reuniao"] else "não")

    proxima = next_assignment(monitor)
    if proxima:
        st.markdown(
            f'<div class="mela-card"><h3>⏭️ Próxima tarefa</h3>'
            f'<p><span class="mela-big">{esc(proxima["ini"])}–{esc(proxima["fim"])}</span><br>'
            f'{esc(proxima["atividade"])} · <b>{esc(proxima["dia"])}</b>'
            f' ({esc(proxima["data"])})</p></div>',
            unsafe_allow_html=True,
        )
    else:
        note("🎉 Sua escala terminou (ou ainda não começou). Aproveita pra descansar.")

    st.markdown("### 🗓️ Sua escala, dia por dia")
    _timeline(monitor, st.session_state.tasks_done)

    total_itens = len(monitor_task_keys(monitor))
    feitos = len(set(monitor_task_keys(monitor)) & set(st.session_state.tasks_done))
    st.progress(min(1.0, feitos / total_itens) if total_itens else 0.0)
    st.caption(f"{feitos} de {total_itens} tarefas marcadas como feitas.")

    st.markdown("")
    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("🗓️ Ver tarefas de todo mundo", width="stretch"):
            go("tarefas")
    with col2:
        if st.button("✅ Tô pronto(a) pro dia", type="primary", width="stretch"):
            track(cfg, store, "pronto", screen="pronto", country=country)
            st.session_state.views.append("pronto")
            st.balloons()
            st.success("Boa! Se cuida e bebe água 💧🍉")


def _activities_rows(atividades: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for act in atividades:
        rows.append(
            {
                "Dia": act.get("dia", ""),
                "Data": act.get("data", ""),
                "Horário": f"{act.get('ini', '')}–{act.get('fim', '')}",
                "Atividade": act.get("atividade", ""),
                "Local": act.get("local", ""),
                "Vagas": act.get("vagas", 0),
                "Escalados": act.get("escalados", 0),
                "Melancias": ", ".join(act.get("monitores") or []),
            }
        )
    return rows


def page_tarefas(data: Mapping[str, Any]) -> None:
    hero("Tarefas de todo mundo", "A escala inteira num lugar só — filtra, acha, respira.", "🗓️")

    atividades = data["atividades"]
    dias = sorted({a.get("dia", "") for a in atividades if a.get("dia")})
    col1, col2 = st.columns([1, 2])
    with col1:
        dia = st.selectbox("📅 Dia", ["Todos"] + dias, key="filtro_dia")
    with col2:
        busca = st.text_input("🔎 Buscar atividade ou local", key="filtro_busca")

    filtradas = atividades
    if dia != "Todos":
        filtradas = [a for a in filtradas if a.get("dia") == dia]
    if busca.strip():
        needle = strip_accents(busca).lower()
        filtradas = [
            a
            for a in filtradas
            if needle in strip_accents(a.get("atividade", "")).lower()
            or needle in strip_accents(a.get("local", "")).lower()
        ]

    if not filtradas:
        st.warning("Nada encontrado com esse filtro 🤔")
        return

    rows = _activities_rows(filtradas)
    try:
        import pandas as pd

        st.dataframe(
            pd.DataFrame(rows),
            width="stretch",
            hide_index=True,
            height=min(560, 45 + 35 * len(rows)),
        )
        csv_bytes = pd.DataFrame(rows).to_csv(index=False).encode("utf-8")
        st.download_button(
            "⬇️ Baixar esta visão em CSV",
            data=csv_bytes,
            file_name="escala_filtrada.csv",
            mime="text/csv",
        )
    except Exception:
        for row in rows:
            st.markdown(
                f"**{esc(row['Dia'])} · {esc(row['Horário'])}** — {esc(row['Atividade'])}  \n"
                f"<span class='mela-small'>{esc(row['Local'])} · "
                f"{row['Escalados']}/{row['Vagas']} melancias</span>",
                unsafe_allow_html=True,
            )

    st.markdown("### 🍉 Quem tá em cada dia")
    cols = st.columns(max(1, len(dias)))
    for col, d in zip(cols, dias, strict=False):
        no_dia = [a for a in atividades if a.get("dia") == d]
        pessoas = {p for a in no_dia for p in (a.get("monitores") or [])}
        col.metric(d, len(no_dia), f"{len(pessoas)} pessoas")

    if st.session_state.get("person"):
        minhas = [a for a in atividades if st.session_state.person in (a.get("monitores") or [])]
        with st.expander(f"📌 Só as minhas ({len(minhas)})", expanded=False):
            for act in minhas:
                st.markdown(
                    f"**{esc(act['dia'])} · {esc(act['ini'])}–{esc(act['fim'])}** — "
                    f"{esc(act['atividade'])}  \n"
                    f"<span class='mela-small'>{esc(act['local'])}</span>",
                    unsafe_allow_html=True,
                )


def page_destaques(data: Mapping[str, Any]) -> None:
    hero(
        "Destaques 🍉",
        "Quem mais somou horas e quem segurou a maratona de pé. Palmas pra vocês!",
        "🏆",
    )
    monitores = data["monitores"]
    ranking = rank_people(monitores)
    if not ranking:
        st.info("Ainda não há escala carregada.")
        return

    top3 = ranking[:3]
    cols = st.columns(len(top3))
    for index, (col, pessoa) in enumerate(zip(cols, top3, strict=False)):
        with col:
            st.markdown(
                f'<div class="mela-podium"><div style="font-size:2.4rem">'
                f'{MEDALS[index] if index < len(MEDALS) else "🍉"}</div>'
                f'<div class="who">{esc(pessoa["nome"])}</div>'
                f'<div class="hrs">{pessoa["horas"]:g}h</div>'
                f'<div class="mela-small">{esc(pessoa["lista"])} · '
                f'{pessoa["funcoes"]} funções</div></div>',
                unsafe_allow_html=True,
            )

    st.markdown("")
    st.success(
        f"🎉 Parabéns, {top3[0]['nome']}! {top3[0]['horas']:g} horas de maratona — "
        "e obrigade a todo mundo que também segurou essa onda. 💚"
    )

    st.markdown("### 📊 Top 10 por horas")
    for position, pessoa in enumerate(ranking[:10], start=1):
        medal = MEDALS[position - 1] if position <= 3 else f"{position}."
        col1, col2 = st.columns([4, 1])
        col1.markdown(
            f"{medal} **{esc(pessoa['nome'])}** "
            f"<span class='mela-small'>· {esc(pessoa['lista'])}</span>",
            unsafe_allow_html=True,
        )
        col2.markdown(f"**{pessoa['horas']:g}h**")

    st.markdown("### 🌟 Superlativos da maratona")
    mais_funcoes = max(monitores, key=lambda m: (m["funcoes"], m["horas"]))
    madrugada = [
        m
        for m in monitores
        if any(parse_hhmm(i.get("ini", "")) is not None and parse_hhmm(i["ini"]) >= 23 * 60
               for d in m.get("dias") or [] for i in d.get("itens") or [])
    ]
    primeira = min(
        (i["ini"] for m in monitores for d in m.get("dias") or [] for i in d.get("itens") or []
         if parse_hhmm(i.get("ini", "")) is not None),
        key=parse_hhmm,
        default="—",
    )
    c1, c2, c3 = st.columns(3)
    c1.metric(
        "🧩 Mais funções",
        mais_funcoes["nome"].split()[0],
        f"{mais_funcoes['funcoes']} funções",
    )
    c2.metric("🌙 Turno da madrugada", f"{len(madrugada)} pessoas", "23h+")
    c3.metric("🌅 Primeiro horário", primeira, "quem abre o dia")

    st.markdown("### 🍉 Todas as melancias")
    blocos = []
    for pessoa in ranking:
        badges = [
            chip(pessoa["lista"], "green"),
            chip(f"{pessoa['horas']:g}h", "gold"),
            chip(f"{pessoa['funcoes']} funções"),
        ]
        if pessoa["reuniao"]:
            badges.append(chip("reunião 02/11 ✅", "green"))
        blocos.append(
            f'<div style="margin:0 0 14px 0"><b>{esc(pessoa["nome"])}</b><br>'
            f'{"".join(badges)}</div>'
        )
    st.markdown("".join(blocos), unsafe_allow_html=True)


PALAVRAS_BOAS = (
    "você tá indo bem 💚",
    "respira, dá tempo",
    "ninguém precisa dar conta sozinho",
    "seu esforço aparece",
    "obrigade por existir nesse time",
    "água, sol e pausa também são trabalho",
    "orgulho de dividir a maratona com você",
    "um passo de cada vez já é caminho",
)


def sanitize_image(raw: bytes, max_side: int = 1600) -> tuple[bytes, str]:
    """Re-encoda a foto sem metadados (EXIF/GPS) e limita o tamanho.

    Se o Pillow não estiver disponível, devolve os bytes originais — o app
    continua funcionando, mas avisa que os metadados não foram removidos.
    """
    try:
        from PIL import Image, ImageOps
    except Exception:  # pragma: no cover - Pillow vem com o Streamlit
        return raw, "original"

    try:
        image = Image.open(io.BytesIO(raw))
        image.load()
        image = ImageOps.exif_transpose(image)
        image.thumbnail((max_side, max_side))
        buffer = io.BytesIO()
        if image.mode in {"RGBA", "LA", "P"}:
            image.convert("RGBA").save(buffer, format="PNG", optimize=True)
            return buffer.getvalue(), "image/png"
        image.convert("RGB").save(buffer, format="JPEG", quality=85, optimize=True)
        return buffer.getvalue(), "image/jpeg"
    except Exception:
        return raw, "original"


def page_meditacao(cfg: Settings, store: AnalyticsStore, country: str) -> None:
    hero(
        "Cantinho da calma",
        "Um espaço pra respirar entre um credenciamento e outro. Sem cobrança. 🧘",
        "🧘",
    )

    col1, col2 = st.columns([1, 1])
    with col1:
        st.markdown(
            '<div class="breath"></div>'
            '<p style="text-align:center" class="mela-small">'
            "inspira 4 · segura 7 · solta 8 — acompanha a bolinha</p>",
            unsafe_allow_html=True,
        )
        st.markdown("#### 🫁 Respiração 4-7-8")
        st.markdown(
            "Senta confortável, solta os ombros e acompanha a animação por 3 ciclos. "
            "Se der vontade de bocejar, é sinal de que funcionou."
        )

    with col2:
        st.markdown("#### 💚 Como você tá agora?")
        humor = st.radio(
            "check-in",
            ["😄 ótimo", "🙂 bem", "😐 neutro", "😕 cansade", "😣 no limite"],
            index=None,
            label_visibility="collapsed",
            key="humor",
        )
        if humor:
            st.session_state.checkin = humor
            if humor.endswith("no limite"):
                note(
                    "Ei, respira. Você não precisa segurar tudo sozinhe. "
                    "Fala com o núcleo — a gente divide essa carga. 🫂"
                )
            elif humor.endswith("cansade"):
                note("Cansaço é informação, não fraqueza. Bebe água e tenta uma pausa de 5 min. 💧")
            else:
                note("Boa! Guarda um pouquinho dessa energia pra você também. ✨")

    st.divider()

    st.markdown("### 💬 Mural de palavras positivas")
    st.caption(
        "As palavras ficam só nesta sessão do navegador — quando você fecha a aba, "
        "elas somem. Nada é salvo no servidor."
    )
    col_input, col_btn = st.columns([4, 1])
    with col_input:
        palavra = st.text_input(
            "Deixa uma palavra boa",
            placeholder="ex.: você consegue, time 💪",
            key="nova_palavra",
            label_visibility="collapsed",
        )
    with col_btn:
        if st.button("Enviar 💌", width="stretch") and palavra.strip():
            st.session_state.words.append(palavra.strip()[:120])
            track(cfg, store, "word", screen="meditacao", country=country,
                  meta={"total": len(st.session_state.words)})

    if st.session_state.words:
        st.markdown(
            "".join(chip(w, "green") for w in st.session_state.words),
            unsafe_allow_html=True,
        )
    else:
        st.markdown(chip(random.choice(PALAVRAS_BOAS), "green"), unsafe_allow_html=True)

    col_a, col_b = st.columns(2)
    if col_a.button("🔀 Sortear uma palavra", width="stretch"):
        st.session_state.words.append(random.choice(PALAVRAS_BOAS))
    if col_b.button("🧹 Limpar mural", width="stretch"):
        st.session_state.words = []
        st.rerun()

    st.divider()

    st.markdown("### 📸 Manda uma foto (que não fica guardada)")
    st.caption(
        "A imagem aparece só pra você, nesta sessão, e é apagada quando você fecha "
        "a aba. A gente remove metadados (EXIF/GPS) antes de exibir. "
        "**Nada é enviado para o servidor.**"
    )
    uploaded = st.file_uploader(
        "Escolhe uma foto",
        type=["png", "jpg", "jpeg", "webp"],
        accept_multiple_files=True,
        key="upload_fotos",
        label_visibility="collapsed",
    )
    if uploaded:
        for file in uploaded:
            raw = file.getvalue()
            if len(raw) > cfg.max_photo_mb * 1024 * 1024:
                st.error(f"{file.name}: passa de {cfg.max_photo_mb} MB, tenta uma menor.")
                continue
            fingerprint = hashlib.sha256(raw).hexdigest()[:16]
            if fingerprint in {p[0] for p in st.session_state.photos}:
                continue
            data, mime = sanitize_image(raw)
            st.session_state.photos.append((fingerprint, data, mime, file.name))
            track(cfg, store, "photo", screen="meditacao", country=country,
                  meta={"count": len(st.session_state.photos)})

    if st.session_state.photos:
        cols = st.columns(min(3, len(st.session_state.photos)))
        for index, (_, data, _mime, name) in enumerate(st.session_state.photos):
            with cols[index % len(cols)]:
                try:
                    st.image(data, caption=name, width="stretch")
                except Exception:
                    st.warning(f"Não consegui exibir {name}.")
        if st.button("🗑️ Apagar fotos desta sessão"):
            st.session_state.photos = []
            st.rerun()
    else:
        st.info("Nenhuma foto por aqui — e é ótimo que você saiba: nada fica salvo. 🍉")


def page_privacidade(cfg: Settings, store: AnalyticsStore) -> None:
    hero("Privacidade, sem letra miúda", "Você decide o que a gente mede. Ponto.", "🔐")

    st.markdown("### 📋 O que é registrado (só com seu ok)")
    st.markdown(
        """
| Dado | Para quê | Fica quanto tempo |
| --- | --- | --- |
| Tela aberta e ordem do caminho | entender onde a orientação trava | 90 dias |
| Tempo aproximado por tela | saber se a página é confusa | 90 dias |
| Nome que você escolheu | te dar o resumo certo e falar com você | 90 dias |
| País de acesso (nunca o IP) | cumprir a regra de acesso ao Brasil | 90 dias |
| Contagem de fotos/palavras | saber se a meditação é usada | 90 dias |
"""
    )
    st.markdown("### 🚫 O que NUNCA é registrado")
    st.markdown(
        "- endereço IP, geolocalização precisa ou operadora;\n"
        "- o conteúdo das suas fotos ou das palavras da meditação;\n"
        "- gravação de tela, áudio ou vídeo;\n"
        "- senhas ou dados de saúde."
    )

    st.markdown("### 🎛️ Seu consentimento")
    estado = st.session_state.get("consent")
    if not cfg.consent_required:
        note("Esta instância está configurada sem exigir consentimento (decisão da organização).")
    elif estado == "granted":
        st.success("Você autorizou o registro de navegação. Obrigade! 💚")
        if st.button("Revogar consentimento e apagar meus dados"):
            removidos = store.delete_sid(st.session_state.get("sid", ""))
            st.session_state.consent = "denied"
            st.session_state.words = []
            st.session_state.photos = []
            st.session_state.views = []
            st.success(f"Pronto: {removidos} registro(s) apagado(s). Nada mais será medido.")
            st.rerun()
    elif estado == "denied":
        st.info("Você escolheu só o essencial: nada está sendo registrado.")
        if st.button("Quero autorizar agora"):
            st.session_state.consent = "granted"
            store.log(st.session_state.sid, "consent", meta={"decision": "granted"})
            st.rerun()
    else:
        st.info("Você ainda não escolheu. O banner no topo da página faz isso.")

    st.markdown("### 🌎 Acesso restrito ao Brasil")
    st.markdown(
        f"O acesso é liberado para conexões com origem no Brasil "
        f"(lista: {', '.join(cfg.allowed_countries)}). Quando o país não pode ser "
        "identificado, a política é "
        f"**{'liberar' if cfg.unknown_country_policy == 'allow' else 'bloquear'}**. "
        "Nenhum IP é armazenado: só o código do país."
    )
    st.caption(
        "Sobre VPN: a checagem é por país de saída da conexão. Não é possível garantir "
        "100% que alguém esteja usando VPN — redes universitárias e operadoras móveis "
        "também compartilham IP. Se você foi bloqueado por engano, fale com a organização."
    )
    if cfg.pixel_url:
        st.markdown("### 👁️ Pixel de acompanhamento")
        st.markdown(
            "Esta instância usa um pixel 1×1 opcional para confirmar a abertura das "
            "telas. Ele só dispara **depois** do seu consentimento e envia apenas o id "
            "anônimo da sessão, a tela e o horário. O endereço é: "
            f"`{esc(cfg.pixel_url)}`"
        )

    st.markdown("### 🧽 Apagar tudo")
    if st.button("Apagar todos os dados desta sessão"):
        removidos = store.delete_sid(st.session_state.get("sid", ""))
        for key in ("words", "photos", "views", "person", "checkin", "tasks_done"):
            st.session_state[key] = [] if isinstance(st.session_state.get(key), list) else ""
        st.success(f"{removidos} registro(s) apagado(s) desta sessão.")
        st.rerun()

    st.caption(
        "Encarregado(a) pelo tratamento de dados: equipe de organização da Maratona. "
        "Pedidos de exclusão também podem ser feitos direto ao núcleo. "
        "O endereço da página pode conter um id de sessão — evite compartilhar o link."
    )


def page_admin(cfg: Settings, store: AnalyticsStore) -> None:
    hero("Painel da organização", "Só pra quem cuida: funil, caminho e saúde da aplicação.", "🛠️")

    if not cfg.admin_password:
        st.warning(
            "Defina a variável de ambiente `ADMIN_PASSWORD` para liberar este painel. "
            "Sem ela, o painel fica fechado por segurança."
        )
        return

    if not st.session_state.get("admin_ok"):
        senha = st.text_input("Senha da organização", type="password", key="admin_pw")
        if st.button("Entrar", type="primary"):
            import hmac as _hmac

            if _hmac.compare_digest(senha, cfg.admin_password):
                st.session_state.admin_ok = True
                track(cfg, store, "admin", screen="admin", meta={"ok": True})
                st.rerun()
            else:
                st.error("Senha incorreta.")
        return

    if store.degraded:
        st.error(
            "⚠️ O banco de dados está em modo memória (disco não gravável). "
            "Os números zeram quando o app reiniciar."
        )

    sessions = store.session_paths()
    report = funnel_report(sessions)

    cols = st.columns(4)
    cols[0].metric("👣 sessões", report["sessoes"])
    cols[1].metric("🙋 identificadas", report["identificadas"])
    cols[2].metric("✅ caminho completo", f"{report['taxa_conclusao'] * 100:.0f}%")
    cols[3].metric("🔀 fora de ordem", report["fora_de_ordem"])

    st.markdown("### 🕳️ Onde o caminho trava")
    for step in CANONICAL_STEPS:
        emoji, label = SCREENS[step]
        aberturas = report["por_tela"].get(step, 0)
        pct = (aberturas / report["sessoes"]) if report["sessoes"] else 0.0
        st.markdown(f"{emoji} **{esc(label)}** — {aberturas} sessão(ões)")
        st.progress(min(1.0, pct))
    if report["abandono"]:
        pior = max(report["abandono"].items(), key=lambda kv: kv[1])
        st.caption(
            f"Maior abandono em **{SCREENS.get(pior[0], ('', pior[0]))[1]}** "
            f"({pior[1]} sessão(ões) pararam ali)."
        )

    st.markdown("### 🧭 Caminho de cada sessão")
    if not sessions:
        st.info("Nenhuma sessão registrada ainda.")
    else:
        import pandas as pd

        rows = []
        for session in sessions[:200]:
            rows.append(
                {
                    "quando": to_local(session["ultimo"], cfg),
                    "pessoa": session["pessoa"] or "—",
                    "país": session["pais"] or "—",
                    "caminho": path_label(session["sequencia"]),
                    "completude": f"{session['completude'] * 100:.0f}%",
                    "status": session["status"],
                    "fora de ordem": "sim" if session["fora_de_ordem"] else "não",
                    "parou em": SCREENS.get(session["parou_em"], ("", session["parou_em"]))[1],
                }
            )
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True, height=380)

    st.markdown("### 🚫 Tentativas bloqueadas")
    blocked = store.blocked()
    if blocked:
        por_pais: dict[str, int] = {}
        for event in blocked:
            pais = event.get("country") or "??"
            por_pais[pais] = por_pais.get(pais, 0) + 1
        st.markdown("".join(chip(f"{pais}: {n}") for pais, n in sorted(por_pais.items())))
    else:
        st.caption("Nenhum bloqueio registrado.")

    st.markdown("### 🧰 Manutenção")
    col1, col2, col3 = st.columns(3)
    if col1.button("🧽 Aplicar retenção agora"):
        removidos = store.purge(cfg.retention_days)
        st.success(
            f"{removidos} evento(s) antigos apagados "
            f"(retenção de {cfg.retention_days} dias)."
        )
    with col2:
        st.download_button(
            "⬇️ Baixar log (CSV)",
            data=store.to_csv().encode("utf-8"),
            file_name="maratona_log.csv",
            mime="text/csv",
            width="stretch",
        )
    if col3.button("🗑️ Apagar tudo", help="Remove todos os eventos do banco"):
        removidos = store.clear_all()
        st.success(f"{removidos} evento(s) apagados.")

    st.caption(
        f"Banco: `{cfg.db_path}` · eventos: {store.count()} · "
        f"retenção: {cfg.retention_days} dias · geo: {cfg.geo_mode}"
    )


# ---------------------------------------------------------------------------
# Montagem da aplicação
# ---------------------------------------------------------------------------


def merge_snapshot_metadata(
    live: dict[str, list[dict[str, Any]]], snapshot: Mapping[str, Any]
) -> dict[str, list[dict[str, Any]]]:
    """Completa lista/reunião do CSV ao vivo com o que só existe no snapshot."""
    indice = {
        strip_accents(_clean(m.get("nome"))).lower(): m
        for m in snapshot.get("monitores") or []
    }
    for monitor in live.get("monitores") or []:
        referencia = indice.get(strip_accents(_clean(monitor.get("nome"))).lower())
        if not referencia:
            continue
        if not monitor.get("lista") or monitor["lista"] == "Escala":
            monitor["lista"] = referencia.get("lista") or monitor["lista"]
        monitor["reuniao"] = bool(referencia.get("reuniao"))
    return live


def build_dataset(csv_text: str | None = None, payload: str | None = None) -> dict[str, Any]:
    """Dataset final: CSV ao vivo (se der) -> snapshot embutido."""
    try:
        snapshot = normalize_dataset(json.loads(payload or DATASET_JSON))
    except (TypeError, ValueError):
        snapshot = {"monitores": [], "atividades": [], "cronograma": []}

    if csv_text:
        parsed = dataset_from_allocations_csv(csv_text)
        if parsed.get("monitores"):
            return merge_snapshot_metadata(parsed, snapshot)
    return snapshot


def fetch_csv(url: str, timeout: float = 8.0) -> str:
    if not url:
        return ""
    try:
        import urllib.request

        req = urllib.request.Request(url, headers={"User-Agent": "melancias/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.read().decode("utf-8", "ignore")
    except Exception:
        return ""


@st.cache_data(ttl=600, show_spinner=False)
def load_dataset_cached(csv_url: str) -> dict[str, Any]:
    return build_dataset(fetch_csv(csv_url))


def read_headers() -> Mapping[str, Any]:
    try:
        return st.context.headers  # type: ignore[attr-defined]
    except Exception:
        return {}


def resolve_access(cfg: Settings) -> dict[str, Any]:
    """Calcula país/VPN uma vez por sessão e guarda no session_state."""
    if st.session_state.get("access") is None:
        lookup = lookup_country_http(cfg.geo_lookup_url) if cfg.geo_lookup_url else None
        st.session_state.access = assess_access(read_headers(), cfg, lookup=lookup)
    return st.session_state.access


def blocked_page(access: Mapping[str, Any]) -> None:
    hero("Acesso restrito 🌎", "Este painel é liberado apenas para conexões no Brasil.", "🚫")
    st.markdown(
        f'<div class="mela-alert">País identificado: <b>{esc(access.get("pais"))}</b> '
        f'· motivo: {esc(access.get("motivo"))}</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        "Se você está no Brasil e caiu aqui, pode ser VPN, rede corporativa ou "
        "proxy da universidade. Desliga a VPN e tenta de novo — ou fala com a "
        "organização que a gente libera na mão."
    )
    if st.button("🔄 Tentar de novo"):
        st.session_state.access = None
        st.rerun()
    st.caption(
        "Nenhum endereço IP é armazenado: só o código do país, quando disponível."
    )


def sidebar(cfg: Settings) -> str:
    ss = st.session_state
    with st.sidebar:
        st.markdown("## 🍉 Maratona de Melancias")
        st.caption(APP_TAGLINE)

        if ss.get("goto"):
            ss["nav"] = ss.pop("goto")

        labels = {key: f"{emoji} {label}" for key, (emoji, label) in SCREENS.items()}
        labels["privacidade"] = "🔐 Privacidade"
        if cfg.admin_password:
            labels["admin"] = "🛠️ Organização"

        nav = st.radio(
            "Navegar",
            list(labels),
            format_func=lambda key: labels[key],
            key="nav",
            label_visibility="collapsed",
        )

        st.divider()
        if ss.get("person"):
            st.markdown(f"**🙋 {esc(ss.person)}**")
            if st.button("Trocar de pessoa", key="side_trocar", width="stretch"):
                ss.person = ""
                go("quem")
        else:
            st.caption("Você ainda não se identificou.")
            if st.button("Quem sou eu?", key="side_quem", width="stretch"):
                go("quem")

        st.divider()
        if cfg.consent_required:
            estado = {"granted": "✅ registrando", "denied": "🙅 só essencial"}.get(
                ss.get("consent") or "", "⏳ aguardando"
            )
            st.caption(f"Privacidade: {estado}")
        st.caption("feito com afeto e melancia 🍉")
    return nav


def render_page(
    nav: str,
    cfg: Settings,
    data: Mapping[str, Any],
    store: AnalyticsStore,
    country: str,
) -> None:
    if nav == "inicio":
        page_inicio(data)
    elif nav == "quem":
        page_quem(cfg, data, store, country)
    elif nav == "resumo":
        page_resumo(cfg, data, store, country)
    elif nav == "tarefas":
        page_tarefas(data)
    elif nav == "destaques":
        page_destaques(data)
    elif nav == "meditacao":
        page_meditacao(cfg, store, country)
    elif nav == "privacidade":
        page_privacidade(cfg, store)
    elif nav == "admin":
        page_admin(cfg, store)
    else:
        page_inicio(data)


def main() -> None:
    st.set_page_config(
        page_title=APP_TITLE,
        page_icon="🍉",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    cfg = Settings.from_env()
    inject_css()
    init_state()

    store = get_store(cfg.db_path)
    if not st.session_state.get("_purged"):
        store.purge(cfg.retention_days)
        st.session_state["_purged"] = True

    access = resolve_access(cfg)
    country = str(access.get("pais") or "")

    if not access.get("liberado", True):
        if analytics_on(cfg) and not st.session_state.get("_blocked_logged"):
            store.log(
                st.session_state.sid,
                "blocked",
                country=country,
                meta={"motivo": access.get("motivo"), "origem": access.get("origem_pais")},
            )
            st.session_state["_blocked_logged"] = True
        blocked_page(access)
        return

    if analytics_on(cfg) and not st.session_state.get("_cookie_synced"):
        cookie_bridge(cfg, st.session_state.sid)
        st.session_state["_cookie_synced"] = True

    consent_banner(cfg, store)
    data = load_dataset_cached(cfg.sheet_csv_url)
    nav = sidebar(cfg)

    if nav in SCREENS:
        stepper(st.session_state.views, nav)
    enter_screen(cfg, store, nav, country)

    try:
        render_page(nav, cfg, data, store, country)
    except Exception as exc:  # a tela nunca morre: mostra o recado e segue
        st.error(
            "😵 Deu um nó aqui nesta tela. O resto do app continua funcionando — "
            "tenta recarregar ou ir para **Início**."
        )
        with st.expander("Detalhes técnicos (para a organização)"):
            st.code(f"{type(exc).__name__}: {exc}")
        if st.button("🍉 Voltar para o início", key="err_home"):
            go("inicio")

    st.markdown("---")
    st.caption(
        f"{APP_TITLE} · {len(data['monitores'])} melancias · "
        f"{len(data['atividades'])} atividades · dados da escala oficial"
    )


if __name__ == "__main__":
    main()
