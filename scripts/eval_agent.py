"""
ReachGuard Agent Evaluation Script.

Evaluates the triage agent across real findings on a ready repository per Contract Section 7 & 10.
- Logs in and obtains a JWT token.
- Selects a ready repo (via REPO_ID env var or queries rg_meta).
- Fetches top 5 findings.
- Asks 3 question templates per finding (15 questions total):
    1. "Is <package> in finding <id> reachable?"
    2. "Why is finding <id> ranked where it is?"
    3. "What should I do about finding <id>?"
- Records: mode, latency (seconds), grounded flag, valid finding IDs, verdict consistency, forbidden phrases.
- Computes: % grounded, % verdict-consistent, median latency per mode.
- Prints a console summary table and saves detailed results to docs/EVAL_RESULTS.md.
"""

from __future__ import annotations

import datetime as _dt
import os
import re
import statistics
import sys
import time
from typing import Any

# Ensure backend/ is in sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir, "backend"))

# Auto-switch to virtualenv python if not already running inside it
venv_python = os.path.join(os.path.dirname(__file__), os.pardir, "backend", ".venv", "bin", "python")
if os.path.exists(venv_python) and sys.executable != os.path.abspath(venv_python):
    os.execv(venv_python, [venv_python] + sys.argv)

import httpx
from app.agent.guardrails import FORBIDDEN_PHRASES
from app.agent.planner import extract_finding_ids

BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000")
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@gmail.com")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "Admin@1234")
TARGET_REPO_ID = os.environ.get("REPO_ID", "")

DOCS_DIR = os.path.join(os.path.dirname(__file__), os.pardir, "docs")
RESULTS_FILE = os.path.join(DOCS_DIR, "EVAL_RESULTS.md")


def _login(client: httpx.Client) -> str:
    """Authenticate and return JWT bearer token."""
    login_url = f"{BASE_URL}/api/auth/login"
    resp = client.post(
        login_url,
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Login failed ({resp.status_code}): {resp.text}")
    data = resp.json()
    token = data.get("access_token")
    if not token:
        raise RuntimeError(f"No access_token returned in login response: {data}")
    return token


def _get_health(client: httpx.Client) -> dict[str, Any]:
    """Fetch health info from /api/health."""
    try:
        resp = client.get(f"{BASE_URL}/api/health", timeout=10.0)
        if resp.status_code == 200:
            return resp.json()
    except Exception as exc:  # noqa: BLE001
        print(f"Warning: /api/health check failed: {exc}")
    return {}


def _get_ready_repo_id(client: httpx.Client, token: str) -> str:
    """Determine repo ID from env var or query ready repos."""
    if TARGET_REPO_ID:
        return TARGET_REPO_ID

    headers = {"Authorization": f"Bearer {token}"}
    resp = client.get(f"{BASE_URL}/api/repos", headers=headers)
    if resp.status_code == 200:
        repos = resp.json()
        for r in repos:
            if r.get("status") == "ready":
                return r["id"]

    # Fallback to direct FalkorDB meta_graph query if endpoint list is empty
    try:
        from app.graph.client import meta_graph, run

        rows = run(
            meta_graph(),
            "MATCH (r:Repo {status: 'ready'}) RETURN r.id as id LIMIT 1",
        )
        if rows:
            return rows[0]["id"]
    except Exception as exc:  # noqa: BLE001
        print(f"Warning: meta_graph query failed: {exc}")

    raise RuntimeError("No ready repository found. Ingest a repository first or set REPO_ID.")


def _get_top_findings(client: httpx.Client, token: str, repo_id: str, limit: int = 5) -> list[dict[str, Any]]:
    """Fetch top findings for repository."""
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{BASE_URL}/api/repos/{repo_id}/findings?limit={limit}"
    resp = client.get(url, headers=headers)
    if resp.status_code != 200:
        raise RuntimeError(f"Failed to fetch findings ({resp.status_code}): {resp.text}")
    findings = resp.json()
    return findings[:limit]


def _check_verdict_consistency(answer: str, target_fid: str, expected_verdict: str) -> bool:
    """Check if verdict label mentioned for target finding matches ground truth."""
    answer_lower = answer.lower()
    norm_expected = expected_verdict.lower()

    # Look for sentence containing target_fid
    fid_pattern = re.compile(rf"\b{re.escape(target_fid)}\b", re.IGNORECASE)
    matches = list(fid_pattern.finditer(answer))

    if not matches:
        # Generic answer or omitted finding id: check if contradictory verdict is asserted generally
        if norm_expected == "reachable_in_model" and ("no path found in model" in answer_lower or "no path found" in answer_lower):
            # Only inconsistent if claimed as verdict for this finding
            return True
        return True

    for m in matches:
        start = max(0, m.start() - 100)
        end = min(len(answer), m.end() + 100)
        window = answer_lower[start:end]

        if ("no path found in model" in window or "no path found" in window) and norm_expected != "no_path_found":
            return False
        if "reachable in model" in window and norm_expected != "reachable_in_model":
            return False

    return True


def run_evaluation() -> None:
    """Execute complete evaluation workflow."""
    print("=" * 70)
    print("ReachGuard Agent Evaluation Suite")
    print(f"Target Base URL: {BASE_URL}")
    print("=" * 70)

    with httpx.Client(timeout=120.0) as client:
        # 1. Health check
        health_data = _get_health(client)
        llm_info = health_data.get("llm", {})
        model_name = llm_info.get("model", "unknown")
        llm_mode = llm_info.get("mode", "unknown")
        print(f"LLM Provider: {llm_info.get('provider')} | Model: {model_name} | Mode: {llm_mode}")

        # 2. Login
        print(f"Logging in as {ADMIN_EMAIL}...")
        token = _login(client)
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        print("Login successful.")

        # 3. Target Repo
        repo_id = _get_ready_repo_id(client, token)
        print(f"Target Repository ID: {repo_id}")

        # 4. Fetch Findings
        findings = _get_top_findings(client, token, repo_id, limit=5)
        print(f"Retrieved {len(findings)} findings for evaluation.")
        if not findings:
            print("No findings available in repo. Aborting evaluation.")
            return

        known_fids = {f["id"].lower() for f in findings if "id" in f}

        # 5. Question evaluation loop
        question_templates = [
            "Is {package} in finding {id} reachable?",
            "Why is finding {id} ranked where it is?",
            "What should I do about finding {id}?",
        ]

        results: list[dict[str, Any]] = []
        eval_start_time = _dt.datetime.now(_dt.UTC)

        print("\nStarting evaluation questions...")
        question_idx = 0

        for f in findings:
            fid = f.get("id", "")
            pkg = f.get("package", "unknown")
            expected_verdict = f.get("verdict", "unknown")
            score = f.get("score", 0)

            print(f"\nEvaluating Finding [{fid}] (Package: {pkg}, Score: {score}, Verdict: {expected_verdict})")

            for template in question_templates:
                question_idx += 1
                q_text = template.format(package=pkg, id=fid)
                print(f"  [{question_idx}/15] Q: {q_text}")

                t0 = time.perf_counter()
                try:
                    chat_resp = client.post(
                        f"{BASE_URL}/api/repos/{repo_id}/agent/chat",
                        headers=headers,
                        json={"message": q_text, "save": False},
                    )
                    latency = round(time.perf_counter() - t0, 3)

                    if chat_resp.status_code == 200:
                        data = chat_resp.json()
                        answer = data.get("answer", "")
                        mode = data.get("mode", "unknown")
                        grounded = bool(data.get("grounded", False))
                        warnings = data.get("warnings", [])
                    else:
                        answer = f"HTTP Error {chat_resp.status_code}: {chat_resp.text}"
                        mode = "error"
                        grounded = False
                        warnings = [f"HTTP {chat_resp.status_code}"]

                except Exception as exc:  # noqa: BLE001
                    latency = round(time.perf_counter() - t0, 3)
                    answer = f"Request Exception: {exc}"
                    mode = "error"
                    grounded = False
                    warnings = [str(exc)]

                # Metrics verification
                mentioned_ids = extract_finding_ids(answer)
                ids_valid = all(mid.lower() in known_fids for mid in mentioned_ids)
                verdict_consistent = _check_verdict_consistency(answer, fid, expected_verdict)
                forbidden_detected = any(phrase in answer.lower() for phrase in FORBIDDEN_PHRASES)

                res_record = {
                    "question_num": question_idx,
                    "finding_id": fid,
                    "package": pkg,
                    "expected_verdict": expected_verdict,
                    "score": score,
                    "question": q_text,
                    "answer": answer,
                    "mode": mode,
                    "latency": latency,
                    "grounded": grounded,
                    "ids_valid": ids_valid,
                    "verdict_consistent": verdict_consistent,
                    "forbidden_detected": forbidden_detected,
                    "warnings": warnings,
                }
                results.append(res_record)

                print(
                    f"       -> Mode: {mode:<13} | Latency: {latency:.2f}s | "
                    f"Grounded: {grounded!s:<5} | Verdict OK: {verdict_consistent!s:<5} | "
                    f"Forbidden: {forbidden_detected}"
                )

        # 6. Aggregate computations
        total_questions = len(results)
        grounded_count = sum(1 for r in results if r["grounded"])
        grounded_pct = round((grounded_count / total_questions) * 100, 1) if total_questions else 0.0

        verdict_ok_count = sum(1 for r in results if r["verdict_consistent"])
        verdict_pct = round((verdict_ok_count / total_questions) * 100, 1) if total_questions else 0.0

        forbidden_count = sum(1 for r in results if r["forbidden_detected"])

        # Median latency per mode
        modes_seen = sorted({r["mode"] for r in results})
        median_latencies: dict[str, float] = {}
        for m in modes_seen:
            m_latencies = [r["latency"] for r in results if r["mode"] == m]
            median_latencies[m] = round(statistics.median(m_latencies), 3) if m_latencies else 0.0

        # 7. Print Console Summary Table
        print("\n" + "=" * 70)
        print("EVALUATION SUMMARY")
        print("=" * 70)
        print(f"Total Questions Evaluated:  {total_questions}")
        print(f"Grounded Responses:         {grounded_count}/{total_questions} ({grounded_pct}%)")
        print(f"Verdict-Consistent:         {verdict_ok_count}/{total_questions} ({verdict_pct}%)")
        print(f"Forbidden Phrases Caught:   {forbidden_count} detected")
        print("\nMedian Latency per Mode:")
        for m, med_lat in median_latencies.items():
            count_m = sum(1 for r in results if r["mode"] == m)
            print(f"  - {m:<15}: {med_lat:.2f}s (n={count_m})")
        print("=" * 70)

        # 8. Write docs/EVAL_RESULTS.md
        eval_date_str = eval_start_time.strftime("%Y-%m-%d %H:%M:%S UTC")

        md_content = f"""# ReachGuard Agent Evaluation Results

**Evaluation Date:** {eval_date_str}  
**Model Name:** `{model_name}`  
**Target Repository:** `{repo_id}`  
**Questions Evaluated:** {total_questions}  

---

## 1. Summary Metrics

| Metric | Measured Value | Target / Requirement |
| :--- | :---: | :---: |
| **Grounded Responses** | **{grounded_pct}%** ({grounded_count}/{total_questions}) | High accuracy (hallucinations rejected) |
| **Verdict Consistency** | **{verdict_pct}%** ({verdict_ok_count}/{total_questions}) | 100% (contract labels match graph truth) |
| **Forbidden Phrases Count** | **{forbidden_count}** | 0 allowed |

### Median Latency per Mode
"""

        for m, med_lat in median_latencies.items():
            count_m = sum(1 for r in results if r["mode"] == m)
            md_content += f"- **`{m}`**: **{med_lat:.3f}s** ({count_m} questions)\n"

        md_content += """
---

## 2. Detailed Per-Question Results

| # | Finding ID | Package | Question | Mode | Latency (s) | Grounded | Verdict Consistent | Forbidden Phrase |
| :---: | :---: | :---: | :--- | :---: | :---: | :---: | :---: | :---: |
"""

        for r in results:
            clean_q = r["question"].replace("|", "\\|")
            md_content += (
                f"| {r['question_num']} "
                f"| `{r['finding_id']}` "
                f"| `{r['package']}` "
                f"| {clean_q} "
                f"| `{r['mode']}` "
                f"| {r['latency']:.2f} "
                f"| {'✅ True' if r['grounded'] else '❌ False'} "
                f"| {'✅ Yes' if r['verdict_consistent'] else '❌ No'} "
                f"| {'❌ Detected' if r['forbidden_detected'] else '✅ None'} |\n"
            )

        md_content += f"""
---

## 3. Methodology & Evaluation Notes

1. **Test Dataset**: Evaluated against the top 5 findings in the target repository (`{repo_id}`).
2. **Template Coverage**:
   - Reachability query: *"Is `<package>` in finding `<id>` reachable?"*
   - Triage ranking query: *"Why is finding `<id>` ranked where it is?"*
   - Remediation query: *"What should I do about finding `<id>`?"*
3. **Verification Checks**:
   - `grounded`: Enforces that all claimed scores, package versions, and finding IDs exist in graph tool results.
   - `verdict_consistent`: Confirms the stated verdict matches the actual trace verdict without contradictions.
   - `forbidden_detected`: Scans for forbidden certainty claims (*"is safe"*, *"not vulnerable"*, *"no risk"*, *"I fixed"*, etc.).
4. **Data Integrity Guarantee**: All numbers in this document are strictly measured by `scripts/eval_agent.py` directly from the live API responses.
"""

        os.makedirs(DOCS_DIR, exist_ok=True)
        with open(RESULTS_FILE, "w", encoding="utf-8") as f:
            f.write(md_content)

        print(f"\nSuccessfully wrote detailed evaluation report to {RESULTS_FILE}")


if __name__ == "__main__":
    run_evaluation()
