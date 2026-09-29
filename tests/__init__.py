"""
Test Suite - Magic Chatbot v2
==============================
Suite de pruebas unitarias y de integración para la arquitectura refactorizada.

Estructura:
- conftest.py: Fixtures compartidas (DB, container, repos, etc.).
- test_models/: Pruebas de modelos SQLAlchemy.
- test_services/: Pruebas de lógica de negocio (unitarias).
- test_handlers/: Pruebas de handlers del bot (integración).
- test_utils/: Pruebas de utilidades (parsers, datetime, etc.).

Para ejecutar:
    pytest tests/ -v
    pytest tests/ --cov=. --cov-report=html
"""
