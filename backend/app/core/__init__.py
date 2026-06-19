"""Core application config package.

Holds cross-cutting, non-DB application wiring (currently the typed env
``Settings`` in ``app.core.config``). A package marker so ``app.core.config``
imports resolve and the hatch wheel (``pyproject.toml`` ``packages = ["app"]``)
ships this directory — mirrors ``app.db``'s package convention.
"""
