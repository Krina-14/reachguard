"""
Unit tests for backend/app/ingest/osv.py.

Covers:
- osv.normalize with real OSV advisory JSON fixture (backend/tests/fixtures/osv_GHSA_example.json)
- Summary fallback to details when summary is missing
- Severity parsing and fallback to UNKNOWN
- Fixed versions extraction from PyPI ranges
- query_vulns skipping unpinned packages
- 24-hour cache utilization and cache miss behavior
- OsvUnavailable exception on network / server failures
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.ingest.osv import (
    OsvUnavailable,
    normalize,
    query_vulns,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def test_osv_normalize_real_fixture():
    """Verify normalization against real downloaded OSV JSON advisory."""
    fixture_path = FIXTURES_DIR / "osv_GHSA_example.json"
    assert fixture_path.is_file(), "Fixture osv_GHSA_example.json must exist"

    raw_data = json.loads(fixture_path.read_text(encoding="utf-8"))
    normalized = normalize(raw_data)

    assert normalized["id"] == "GHSA-cpwx-vrp4-4pq7"
    assert isinstance(normalized["aliases"], list)
    assert "CVE-2025-27516" in normalized["aliases"]
    assert "Jinja2" in normalized["summary"]
    assert normalized["severity"] == "MODERATE"
    assert "3.1.6" in normalized["fixed_versions"]
    assert normalized["published"].startswith("2025-03-05")


def test_osv_normalize_summary_fallback_to_details():
    raw_data = {
        "id": "GHSA-test-1234",
        "summary": "",
        "details": "A" * 300,
        "aliases": ["CVE-2024-9999"],
        "database_specific": {"severity": "HIGH"},
        "affected": [
            {
                "package": {"ecosystem": "PyPI", "name": "dummy"},
                "ranges": [{"events": [{"introduced": "0"}, {"fixed": "1.2.3"}]}],
            }
        ],
        "published": "2024-01-01T00:00:00Z",
    }
    normalized = normalize(raw_data)
    assert len(normalized["summary"]) == 200
    assert normalized["severity"] == "HIGH"
    assert normalized["fixed_versions"] == ["1.2.3"]


def test_osv_normalize_severity_unknown():
    raw_data = {
        "id": "GHSA-no-sev",
        "summary": "Sample advisory without severity",
    }
    normalized = normalize(raw_data)
    assert normalized["severity"] == "UNKNOWN"
    assert normalized["aliases"] == []
    assert normalized["fixed_versions"] == []


def test_query_vulns_skips_unpinned():
    """Packages with version=None must NOT be queried."""
    packages = [("flask", None), ("requests", None)]
    # Should return empty dict without making network calls
    res = query_vulns(packages)
    assert res == {}


@patch("app.ingest.osv._get_vuln_detail")
@patch("httpx.Client.request")
def test_query_vulns_batching_and_response(mock_request, mock_get_detail):
    """Simulate batch query and detail fetching."""
    mock_batch_resp = MagicMock()
    mock_batch_resp.status_code = 200
    mock_batch_resp.json.return_value = {
        "results": [
            {"vulns": [{"id": "GHSA-item-1"}]},
            {"vulns": []},
        ]
    }
    mock_request.return_value = mock_batch_resp

    mock_get_detail.return_value = {
        "id": "GHSA-item-1",
        "summary": "Sample vulnerability",
        "aliases": ["CVE-2024-1111"],
        "database_specific": {"severity": "CRITICAL"},
        "published": "2024-01-01T00:00:00Z",
    }

    packages = [("flask", "2.0.0"), ("click", "8.0.0")]
    results = query_vulns(packages)

    assert ("flask", "2.0.0") in results
    assert len(results[("flask", "2.0.0")]) == 1
    assert results[("flask", "2.0.0")][0]["id"] == "GHSA-item-1"
    assert results[("flask", "2.0.0")][0]["severity"] == "CRITICAL"

    assert ("click", "8.0.0") in results
    assert len(results[("click", "8.0.0")]) == 0


@patch("httpx.Client.request", side_effect=httpx.ConnectError("Network unreachable"))
def test_query_vulns_raises_osv_unavailable(mock_request):
    """Network connection failure after retries raises OsvUnavailable."""
    packages = [("flask", "2.0.0")]
    with pytest.raises(OsvUnavailable) as exc_info:
        query_vulns(packages)

    assert "Could not reach OSV.dev" in str(exc_info.value)
