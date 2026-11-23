"""Offline checks of the dependency pinning policy (the online date check is scripts/check_dependencies.py)."""

from __future__ import annotations

import importlib.util
import sys

from tests.pglite_server import PROJECT_ROOT

spec = importlib.util.spec_from_file_location("check_dependencies", PROJECT_ROOT / "scripts" / "check_dependencies.py")
check_dependencies = importlib.util.module_from_spec(spec)
sys.modules["check_dependencies"] = check_dependencies
spec.loader.exec_module(check_dependencies)


def test_python_requirements_are_exactly_pinned():
    packages, errors = check_dependencies.read_requirements(PROJECT_ROOT / "requirements-dev.txt")
    assert errors == []
    names = {p.name.lower() for p in packages}
    assert {"fastapi", "pydantic", "sqlalchemy", "alembic", "psycopg2-binary", "pytest", "httpx", "uvicorn"} <= names
    assert len(names) == len(packages), "a package is listed twice"


def test_npm_packages_are_exactly_pinned_and_locked():
    packages, errors = check_dependencies.read_npm_lock()
    assert errors == []
    locked = {p.name: p.version for p in packages}
    assert locked["@electric-sql/pglite"] == "0.5.8"
    assert locked["@electric-sql/pglite-socket"] == "0.2.11"


def test_installed_environment_matches_the_pins():
    packages, _ = check_dependencies.read_requirements(PROJECT_ROOT / "requirements-dev.txt")
    assert check_dependencies.check_installed(packages) == []


def test_supported_python_version():
    assert (3, 12) <= sys.version_info[:2] <= (3, 13)
