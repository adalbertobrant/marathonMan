"""Regera o .ics estático publicado em docs/.

O arquivo é gerado com um DTSTAMP fixo para o resultado ser reprodutível: assim
o teste `test_arquivo_estatico_esta_sincronizado` consegue detectar quando a
programação mudou e o arquivo publicado ficou velho.

Uso: make ics
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app  # noqa: E402

DESTINO = ROOT / "docs" / "programacao-final-sbc-2026.ics"
DTSTAMP_FIXO = datetime(2026, 11, 5, 0, 0, tzinfo=timezone.utc)


def main() -> None:
    with DESTINO.open("w", encoding="utf-8", newline="") as arquivo:
        arquivo.write(app.build_ics(DTSTAMP_FIXO))
    print(f"escrito: {DESTINO.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
