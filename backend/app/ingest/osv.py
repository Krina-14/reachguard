"""
ReachGuard — OSV.dev Vulnerability Scanner Client.

Queries OSV.dev batch API for PyPI packages, caches advisory responses locally,
and normalizes vulnerability records according to the shared contract.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 24 * 60 * 60  # 24 hours


class OsvUnavailable(Exception):
    """Raised when the OSV.dev API cannot be reached after retries."""


def get_cache_dir() -> Path:
    """Return cache directory, falling back to WORK_DIR if OSV_CACHE_DIR is not writable."""
    target = Path(settings.OSV_CACHE_DIR)
    try:
        target.mkdir(parents=True, exist_ok=True)
        return target
    except OSError:
        fallback = Path(settings.WORK_DIR) / "osv_cache"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def normalize(vuln_json: dict[str, Any]) -> dict[str, Any]:
    """
    Normalize an OSV vulnerability record to the contract schema.

    Schema:
    - id: str (OSV or GHSA ID)
    - aliases: list[str] (e.g. CVE-...)
    - summary: str (summary or first 200 chars of details)
    - severity: str (LOW | MODERATE | HIGH | CRITICAL | UNKNOWN)
    - fixed_versions: list[str] (versions from PyPI ranges containing 'fixed')
    - published: str (ISO datetime or date)
    """
    vuln_id = vuln_json.get("id", "")

    # Aliases
    aliases = vuln_json.get("aliases", [])
    if not isinstance(aliases, list):
        aliases = []

    # Summary or first 200 chars of details
    summary = vuln_json.get("summary", "")
    if not summary:
        details = vuln_json.get("details", "")
        summary = details[:200] if details else ""

    # Severity: check database_specific.severity, then cvss/severity objects
    severity = "UNKNOWN"
    db_spec = vuln_json.get("database_specific", {})
    if isinstance(db_spec, dict) and "severity" in db_spec:
        raw_sev = str(db_spec["severity"]).upper()
        if raw_sev in ("LOW", "MODERATE", "MEDIUM", "HIGH", "CRITICAL"):
            severity = "MODERATE" if raw_sev == "MEDIUM" else raw_sev

    if severity == "UNKNOWN":
        # Check top-level severity field (CVSS v3/v4 score or list)
        sev_list = vuln_json.get("severity", [])
        if isinstance(sev_list, list):
            for s in sev_list:
                if isinstance(s, dict) and "score" in s:
                    score_str = str(s["score"])
                    # Heuristic CVSS vector inspection
                    if "CVSS:" in score_str:
                        severity = "UNKNOWN"

    # Fixed versions from affected PyPI packages
    fixed_versions: list[str] = []
    affected = vuln_json.get("affected", [])
    if isinstance(affected, list):
        for aff in affected:
            if not isinstance(aff, dict):
                continue
            pkg = aff.get("package", {})
            eco = pkg.get("ecosystem", "PyPI")
            if eco and eco.lower() == "pypi":
                ranges = aff.get("ranges", [])
                if isinstance(ranges, list):
                    for rng in ranges:
                        if not isinstance(rng, dict):
                            continue
                        events = rng.get("events", [])
                        if isinstance(events, list):
                            for evt in events:
                                if isinstance(evt, dict) and "fixed" in evt:
                                    fix = str(evt["fixed"]).strip()
                                    if fix and fix not in fixed_versions:
                                        fixed_versions.append(fix)

    published = str(vuln_json.get("published", ""))

    return {
        "id": vuln_id,
        "aliases": aliases,
        "summary": summary,
        "severity": severity,
        "fixed_versions": fixed_versions,
        "published": published,
    }


def _fetch_with_retries(
    client: httpx.Client,
    method: str,
    url: str,
    max_retries: int = 3,
    **kwargs: Any,
) -> httpx.Response:
    """Send an HTTP request with exponential backoff retries."""
    backoff = 0.5
    last_exc: Exception | None = None

    for _attempt in range(max_retries):
        try:
            resp = client.request(method, url, **kwargs)
            if resp.status_code >= 500:
                time.sleep(backoff)
                backoff *= 2
                continue
            return resp
        except (httpx.RequestError, httpx.TimeoutException) as exc:
            last_exc = exc
            time.sleep(backoff)
            backoff *= 2

    logger.error("OSV request failed after %d attempts: %s", max_retries, url)
    raise OsvUnavailable(f"Could not reach OSV.dev: {last_exc}") from last_exc


def _get_vuln_detail(
    vuln_id: str,
    client: httpx.Client,
    base_url: str,
    cache_dir: Path,
) -> dict[str, Any] | None:
    """Fetch vulnerability JSON with 24h disk caching."""
    cache_file = cache_dir / f"{vuln_id}.json"

    # Check cache freshness (younger than 24 hours)
    if cache_file.is_file():
        try:
            st = cache_file.stat()
            if time.time() - st.st_mtime < CACHE_TTL_SECONDS:
                data = json.loads(cache_file.read_text(encoding="utf-8"))
                if isinstance(data, dict) and data.get("id"):
                    return data
        except (OSError, json.JSONDecodeError):
            pass

    # Cache miss or stale -> fetch from OSV.dev
    url = f"{base_url.rstrip('/')}/v1/vulns/{vuln_id}"
    resp = _fetch_with_retries(client, "GET", url)
    if resp.status_code == 200:
        data = resp.json()
        try:
            cache_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except OSError as exc:
            logger.warning("Could not write OSV cache file %s: %s", cache_file, exc)
        return data
    elif resp.status_code == 404:
        return None
    else:
        raise OsvUnavailable(f"Could not reach OSV.dev: HTTP {resp.status_code}")


def query_vulns(
    packages: list[tuple[str, str | None]],
    base_url: str | None = None,
    timeout: float = 20.0,
) -> dict[tuple[str, str], list[dict[str, Any]]]:
    """
    Query OSV.dev batch API for vulnerabilities affecting packages.

    Args:
        packages: List of (name, version) tuples. Packages with version=None are ignored.
        base_url: OSV API base URL (defaults to settings.OSV_BASE_URL).
        timeout: Request timeout in seconds.

    Returns:
        Dict mapping (name, version) -> list of normalized vulnerability records.

    Raises:
        OsvUnavailable: If OSV.dev cannot be reached after retries.
    """
    if base_url is None:
        base_url = settings.OSV_BASE_URL

    cache_dir = get_cache_dir()

    # Filter only packages with a pinned version
    query_pkgs: list[tuple[str, str]] = [
        (name, version) for name, version in packages if version is not None
    ]

    results: dict[tuple[str, str], list[dict[str, Any]]] = {
        (n, v): [] for n, v in query_pkgs
    }
    if not query_pkgs:
        return results

    batch_size = 100
    distinct_vuln_ids: set[str] = set()
    pkg_vuln_id_map: dict[tuple[str, str], list[str]] = {
        (n, v): [] for n, v in query_pkgs
    }

    transport = httpx.HTTPTransport(retries=0)
    with httpx.Client(timeout=timeout, transport=transport) as client:
        # Step 1: Batch queries in chunks of 100
        for i in range(0, len(query_pkgs), batch_size):
            chunk = query_pkgs[i : i + batch_size]
            body = {
                "queries": [
                    {"package": {"name": n, "ecosystem": "PyPI"}, "version": v}
                    for n, v in chunk
                ]
            }

            url = f"{base_url.rstrip('/')}/v1/querybatch"
            resp = _fetch_with_retries(client, "POST", url, json=body)
            if resp.status_code != 200:
                raise OsvUnavailable(f"Could not reach OSV.dev: HTTP {resp.status_code}")

            batch_resp = resp.json()
            query_results = batch_resp.get("results", [])

            for (pkg_name, pkg_ver), item in zip(chunk, query_results, strict=False):
                vulns = item.get("vulns", [])
                for v in vulns:
                    vid = v.get("id")
                    if vid:
                        distinct_vuln_ids.add(vid)
                        pkg_vuln_id_map[(pkg_name, pkg_ver)].append(vid)

        # Step 2: Fetch and normalize details for distinct vulnerability IDs
        vuln_details_map: dict[str, dict[str, Any]] = {}
        for vid in distinct_vuln_ids:
            raw_detail = _get_vuln_detail(vid, client, base_url, cache_dir)
            if raw_detail:
                vuln_details_map[vid] = normalize(raw_detail)

    # Assemble normalized output map
    for (n, v), vids in pkg_vuln_id_map.items():
        results[(n, v)] = [
            vuln_details_map[vid] for vid in vids if vid in vuln_details_map
        ]

    return results
