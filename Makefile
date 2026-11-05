.PHONY: help install run test cov lint check clean

PY := .venv/bin/python
PIP := uv pip install --python $(PY)

help:
	@echo "install  cria .venv e instala dependências"
	@echo "run      sobe o app em http://localhost:8501"
	@echo "test     roda a suíte de testes"
	@echo "cov      testes com cobertura"
	@echo "lint     ruff (checagem)"
	@echo "check    lint + testes (o que o CI faz)"

install:
	uv venv --python 3.11 .venv
	$(PIP) -r requirements-dev.txt

run:
	$(PY) -m streamlit run app.py

test:
	$(PY) -m pytest

cov:
	$(PY) -m pytest --cov=app --cov-report=term-missing --cov-fail-under=80

lint:
	.venv/bin/ruff check app.py tests

check: lint test

clean:
	rm -rf .pytest_cache .ruff_cache .coverage htmlcov
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
