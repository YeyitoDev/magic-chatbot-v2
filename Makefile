.PHONY: help install test lint run jobs clean db-seed

help:
	@echo "Magic Chatbot v2 - Comandos"
	@echo "  make install   - Instalar dependencias"
	@echo "  make test      - Ejecutar tests"
	@echo "  make lint      - Lint con Ruff"
	@echo "  make run       - Iniciar bot (polling)"
	@echo "  make jobs      - Iniciar solo los jobs programados"
	@echo "  make clean     - Limpiar caché + logs"
	@echo "  make db-seed   - Sembrar precios por defecto si la tabla está vacía"

install:
	pip install -r requirements.txt

test:
	python -m pytest

lint:
	ruff check .

run:
	python main.py

jobs:
	python main.py --jobs-only

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	rm -rf logs/*.log 2>/dev/null || true

db-seed:
	python -c "from core.container import container; container.initialize_defaults(); print('DB seeded')"
