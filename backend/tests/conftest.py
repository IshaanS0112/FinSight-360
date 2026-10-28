"""Shared fixtures.

Two kinds of test live in this suite.

The **engine tests** exercise the pure computation functions directly - no
database, no network, no model. That is deliberate: every claim this project
makes (the ratios are arithmetic, the Altman coefficients are the published ones,
the right model variant is chosen for the sector, a missing input is omitted
rather than zeroed, the report degrades without an API key) is a claim about those
functions. Anyone who clones the repo can check all of it with ``pytest`` and
nothing running.

The **API tests** run the real FastAPI app against a temporary SQLite file. The
models declare JSONB and UUID as dialect *variants*, so the same schema loads on
SQLite - which means the HTTP contract is tested on a fresh clone with no
Postgres container up, rather than being the one layer nobody ever runs.

The three company fixtures are the real sourced filings, loaded from
``data/sample_filings/``. Using the actual data files rather than inline
dictionaries means a test failure after editing a filing is a real signal, not a
fixture drifting out of sync with the data.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

# Must happen before app.config is imported anywhere: get_settings is cached, so
# the first read of DATABASE_URL is the one that sticks.
_TMP_DB = Path(tempfile.mkdtemp(prefix="finsight360-tests-")) / "test.db"
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP_DB}"
os.environ.setdefault("ANTHROPIC_API_KEY", "")

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))
FILINGS_DIR = BACKEND_ROOT.parent / "data" / "sample_filings"

from app.config import Settings  # noqa: E402
from app.services.benchmarks import load_reference_bands  # noqa: E402
from app.services.line_items import merge_statements  # noqa: E402


def load_filing(stem: str) -> dict[str, Any]:
    path = FILINGS_DIR / f"{stem}.json"
    assert path.is_file(), f"missing sample filing: {path}"
    return json.loads(path.read_text())


def filing_line_items(filing: dict[str, Any]) -> dict[str, float]:
    return merge_statements([(s["statement_type"], s["line_items"]) for s in filing["statements"]])


@pytest.fixture
def settings() -> Settings:
    """Default parameter set, isolated from any .env on the developer's machine."""
    return Settings(_env_file=None)


@pytest.fixture
def reference_table() -> tuple[dict[str, dict[str, float]], str]:
    return load_reference_bands(None)


# --- The three sourced filings ------------------------------------------------


@pytest.fixture
def caterpillar() -> dict[str, Any]:
    return load_filing("caterpillar_fy2024")


@pytest.fixture
def infosys() -> dict[str, Any]:
    return load_filing("infosys_fy2024")


@pytest.fixture
def vodafone_idea() -> dict[str, Any]:
    return load_filing("vodafone_idea_fy2024")


@pytest.fixture
def cat_items(caterpillar: dict[str, Any]) -> dict[str, float]:
    return filing_line_items(caterpillar)


@pytest.fixture
def infy_items(infosys: dict[str, Any]) -> dict[str, float]:
    return filing_line_items(infosys)


@pytest.fixture
def vi_items(vodafone_idea: dict[str, Any]) -> dict[str, float]:
    return filing_line_items(vodafone_idea)


@pytest.fixture
def client():
    """FastAPI TestClient over a fresh SQLite schema."""
    from fastapi.testclient import TestClient

    from app.db.session import Base, engine
    from app.main import app

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with TestClient(app) as test_client:
        yield test_client
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def load_company(client):
    """Create a company from a filing dict and upload its statements."""

    def _load(filing: dict[str, Any]) -> str:
        response = client.post("/companies", json=filing["company"])
        assert response.status_code == 201, response.text
        company_id = response.json()["id"]
        for statement in filing["statements"]:
            uploaded = client.post(f"/companies/{company_id}/financial-statements", json=statement)
            assert uploaded.status_code == 201, uploaded.text
        return company_id

    return _load
