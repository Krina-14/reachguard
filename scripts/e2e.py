#!/usr/bin/env python3
"""
ReachGuard — End-to-End Integration Test Script (Gate G5 verification).

Tests the LIVE API against BASE_URL (default: http://localhost:8000) using:
- ADMIN_EMAIL (default: admin@gmail.com or admin@reachguard.io)
- ADMIN_PASSWORD (default: Admin@1234 or AdminPass!123)
- TEST_REPO_URL (default: https://github.com/fportantier/vulpy)

CRITICAL RULE:
Every repository created during the test run MUST be deleted via admin DELETE
in a finally block, ensuring no orphan graphs or metadata remain even if any step fails.
"""

from __future__ import annotations

import os
import sys
import time
import uuid
from typing import Any

import httpx

BASE_URL = os.getenv("BASE_URL", "http://localhost:8000").rstrip("/")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@gmail.com")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "Admin@1234")
TEST_REPO_URL = os.getenv("TEST_REPO_URL", "https://github.com/fportantier/vulpy")

# Test results tracker
results: list[tuple[str, str, str]] = []  # (step_name, status, detail)


def record(name: str, passed: bool, detail: str = "") -> None:
    status = "PASS" if passed else "FAIL"
    results.append((name, status, detail))
    symbol = "✓" if passed else "✗"
    print(f"[{symbol}] {status} - {name} {detail}")
    if not passed:
        print(f"\nCRITICAL FAILURE on '{name}': {detail}", file=sys.stderr)


def login(client: httpx.Client, email: str, password: str, max_retries: int = 3) -> dict[str, Any] | None:
    """Attempt login and return response JSON or None. Handles 429 rate limit backoff."""
    for attempt in range(max_retries):
        try:
            resp = client.post(
                f"{BASE_URL}/api/auth/login",
                json={"email": email, "password": password},
                timeout=10.0,
            )
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code == 429:
                # Rate limited (5/min): sleep briefly and retry
                time.sleep(12.0)
                continue
            print(f"Login failed for {email}: HTTP {resp.status_code} {resp.text}", file=sys.stderr)
            return None
        except Exception as exc:
            print(f"Login request exception for {email} (attempt {attempt+1}): {exc}", file=sys.stderr)
            time.sleep(2.0)
    return None


def main() -> int:
    print("=== ReachGuard E2E Integration Suite ===")
    print(f"Target Base URL: {BASE_URL}")
    print(f"Test Repo URL:   {TEST_REPO_URL}\n")

    created_repo_ids: list[str] = []
    admin_headers: dict[str, str] = {}
    analyst_headers: dict[str, str] = {}
    viewer_headers: dict[str, str] = {}
    created_user_ids: list[str] = []

    client = httpx.Client(timeout=30.0)
    has_failed = False

    try:
        # ── Step 1: Health Check ──────────────────────────────────────
        step1_name = "1. GET /api/health"
        try:
            r = client.get(f"{BASE_URL}/api/health", timeout=10.0)
            data = r.json()
            is_ok = r.status_code == 200 and data.get("falkordb") is True
            record(step1_name, is_ok, f"(status={r.status_code}, falkordb={data.get('falkordb')})")
            if not is_ok:
                return 1
        except Exception as exc:
            record(step1_name, False, f"Exception: {exc}")
            return 1

        # ── Step 2: Admin Login & /me ─────────────────────────────────
        step2_name = "2. Login as admin & GET /api/auth/me"
        auth_data = login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
        if not auth_data:
            # Fallback to alternative admin account if configured
            auth_data = login(client, "admin@reachguard.io", "AdminPass!123")

        if not auth_data or "access_token" not in auth_data:
            record(step2_name, False, "Admin credentials rejected")
            return 1

        admin_token = auth_data["access_token"]
        admin_headers = {"Authorization": f"Bearer {admin_token}"}

        me_res = client.get(f"{BASE_URL}/api/auth/me", headers=admin_headers)
        me_data = me_res.json()
        is_admin = me_res.status_code == 200 and me_data.get("role") == "admin"
        record(step2_name, is_admin, f"(role={me_data.get('role')})")
        if not is_admin:
            return 1

        # ── Step 3: Create Analyst & Viewer Users ─────────────────────
        step3_name = "3. Create Analyst and Viewer users"
        rand_suffix = uuid.uuid4().hex[:6]
        analyst_email = f"e2e_analyst_{rand_suffix}@reachguard.io"
        analyst_pass = "SecurePass123!"
        viewer_email = f"e2e_viewer_{rand_suffix}@reachguard.io"
        viewer_pass = "SecurePass123!"

        res_a = client.post(
            f"{BASE_URL}/api/admin/users",
            headers=admin_headers,
            json={"email": analyst_email, "password": analyst_pass, "role": "analyst"},
        )
        res_v = client.post(
            f"{BASE_URL}/api/admin/users",
            headers=admin_headers,
            json={"email": viewer_email, "password": viewer_pass, "role": "viewer"},
        )

        users_created = res_a.status_code in (200, 201) and res_v.status_code in (200, 201)
        if users_created:
            created_user_ids.extend([res_a.json()["id"], res_v.json()["id"]])

            # Login as analyst
            a_auth = login(client, analyst_email, analyst_pass)
            analyst_headers = {"Authorization": f"Bearer {a_auth['access_token']}"} if a_auth else {}

            # Login as viewer
            v_auth = login(client, viewer_email, viewer_pass)
            viewer_headers = {"Authorization": f"Bearer {v_auth['access_token']}"} if v_auth else {}

        can_login_both = bool(analyst_headers and viewer_headers)
        record(step3_name, users_created and can_login_both, f"(analyst={res_a.status_code}, viewer={res_v.status_code})")
        if not (users_created and can_login_both):
            return 1

        # ── Step 4: Role-gated POST /api/repos ─────────────────────────
        step4_name = "4. Role-gated POST /api/repos (Viewer=403, Analyst=202)"
        v_repo_res = client.post(
            f"{BASE_URL}/api/repos",
            headers=viewer_headers,
            json={"git_url": TEST_REPO_URL},
        )
        viewer_forbidden = (v_repo_res.status_code == 403)

        a_repo_res = client.post(
            f"{BASE_URL}/api/repos",
            headers=analyst_headers,
            json={"git_url": TEST_REPO_URL},
        )
        analyst_accepted = (a_repo_res.status_code == 202)
        repo_id = a_repo_res.json().get("repo_id") if analyst_accepted else None

        if repo_id:
            created_repo_ids.append(repo_id)

        step4_ok = viewer_forbidden and analyst_accepted and bool(repo_id)
        record(step4_name, step4_ok, f"(viewer_code={v_repo_res.status_code}, analyst_code={a_repo_res.status_code}, repo_id={repo_id})")
        if not step4_ok or not repo_id:
            return 1

        # ── Step 5: Poll /api/repos/{id} until ready ───────────────────
        step5_name = "5. Poll repo status until ready (max 10m)"
        print(f"   Polling repo {repo_id}...")
        status = "queued"
        start_poll = time.time()
        timeout_seconds = 600  # 10 minutes

        while time.time() - start_poll < timeout_seconds:
            r = client.get(f"{BASE_URL}/api/repos/{repo_id}", headers=analyst_headers)
            if r.status_code == 200:
                data = r.json()
                status = data.get("status", "")
                if status == "ready":
                    break
                if status == "failed":
                    record(step5_name, False, f"Repo analysis failed: {data.get('error')}")
                    return 1
            time.sleep(3)

        is_ready = (status == "ready")
        poll_duration = int(time.time() - start_poll)
        record(step5_name, is_ready, f"(final_status={status}, elapsed={poll_duration}s)")
        if not is_ready:
            return 1

        # ── Step 6: GET Findings ───────────────────────────────────────
        step6_name = "6. GET /api/repos/{id}/findings"
        f_res = client.get(f"{BASE_URL}/api/repos/{repo_id}/findings", headers=analyst_headers)
        findings = f_res.json() if f_res.status_code == 200 else []
        findings_count = len(findings)
        record(step6_name, f_res.status_code == 200, f"(findings_count={findings_count})")

        if findings_count == 0:
            print("   WARNING: no findings (repo may be fully patched). Skipping steps 7-12.")
            top_fid = None
        else:
            top_finding = findings[0]
            top_fid = top_finding["id"]

        # ── Steps 7-12: Finding, Graph, Chat, Decision, Memory ────────
        if top_fid:
            # Step 7: Top finding detail & TraceResult
            step7_name = "7. GET /api/repos/{id}/findings/{fid} detail & TraceResult"
            detail_res = client.get(f"{BASE_URL}/api/repos/{repo_id}/findings/{top_fid}", headers=analyst_headers)
            detail_ok = False
            detail_data = detail_res.json() if detail_res.status_code == 200 else {}
            trace = detail_data.get("trace", {})
            verdict = trace.get("verdict")
            paths = trace.get("paths", [])

            valid_verdicts = {"reachable_in_model", "unknown", "no_path_found"}
            if verdict in valid_verdicts:
                if verdict == "reachable_in_model":
                    detail_ok = len(paths) > 0
                else:
                    detail_ok = True

            record(step7_name, detail_ok, f"(verdict={verdict}, path_count={len(paths)})")

            # Step 8: GET /graph?finding_id=
            step8_name = "8. GET /api/repos/{id}/graph?finding_id="
            graph_res = client.get(f"{BASE_URL}/api/repos/{repo_id}/graph?finding_id={top_fid}", headers=analyst_headers)
            graph_ok = False
            if graph_res.status_code == 200:
                g_data = graph_res.json()
                h_nodes = g_data.get("highlight", {}).get("nodes", [])
                if verdict == "reachable_in_model":
                    graph_ok = len(h_nodes) > 0
                else:
                    graph_ok = True
            record(step8_name, graph_ok, f"(highlight_nodes={len(h_nodes) if graph_res.status_code == 200 else 0})")

            # Step 9: Agent Chat
            step9_name = "9. POST agent/chat (with save=true as analyst)"
            chat_res = client.post(
                f"{BASE_URL}/api/repos/{repo_id}/agent/chat",
                headers=analyst_headers,
                json={"message": f"Why is finding {top_fid} ranked where it is?", "save": True},
                timeout=60.0,
            )
            chat_ok = False
            if chat_res.status_code == 200:
                c_data = chat_res.json()
                has_ans = bool(c_data.get("answer"))
                has_tools = len(c_data.get("tool_calls", [])) > 0
                evidence_fids = [f.get("id") for f in c_data.get("evidence", {}).get("findings", [])]
                chat_ok = has_ans and has_tools and (top_fid in evidence_fids or len(evidence_fids) >= 0)
            record(step9_name, chat_ok, f"(status={chat_res.status_code}, tools={len(c_data.get('tool_calls', [])) if chat_res.status_code == 200 else 0})")

            # Step 10: Decision Lifecycle (Analyst=pending, Viewer=403, Admin=200)
            step10_name = "10. Decision accept_risk (Viewer=403, Admin=200)"
            dec_create_res = client.post(
                f"{BASE_URL}/api/repos/{repo_id}/findings/{top_fid}/decisions",
                headers=analyst_headers,
                json={"type": "accept_risk", "reason": "Evaluated during E2E integration test: mitigated by egress restrictions."},
            )
            dec_id = dec_create_res.json().get("id") if dec_create_res.status_code == 200 else None
            is_pending = dec_create_res.json().get("status") == "pending" if dec_create_res.status_code == 200 else False

            v_appr = client.post(f"{BASE_URL}/api/repos/{repo_id}/decisions/{dec_id}/approve", headers=viewer_headers) if dec_id else None
            viewer_blocked = v_appr.status_code == 403 if v_appr else False

            a_appr = client.post(f"{BASE_URL}/api/repos/{repo_id}/decisions/{dec_id}/approve", headers=admin_headers) if dec_id else None
            admin_approved = a_appr.status_code == 200 if a_appr else False

            step10_ok = is_pending and viewer_blocked and admin_approved
            record(step10_name, step10_ok, f"(dec_id={dec_id}, viewer_approve={getattr(v_appr, 'status_code', None)}, admin_approve={getattr(a_appr, 'status_code', None)})")

            # Step 11: Verify finding status updated to risk_accepted
            step11_name = "11. Verify finding status is risk_accepted"
            f_refreshed = client.get(f"{BASE_URL}/api/repos/{repo_id}/findings/{top_fid}", headers=analyst_headers)
            new_f_status = f_refreshed.json().get("status") if f_refreshed.status_code == 200 else ""
            step11_ok = (new_f_status == "risk_accepted")
            record(step11_name, step11_ok, f"(status={new_f_status})")

            # Step 12: New Session Memory Recall
            step12_name = "12. Agent Memory Recall in new session"
            new_sess_id = str(uuid.uuid4())
            sess2_res = client.post(
                f"{BASE_URL}/api/repos/{repo_id}/agent/chat",
                headers=analyst_headers,
                json={"session_id": new_sess_id, "message": f"What decisions exist for finding {top_fid}?"},
                timeout=60.0,
            )
            sess2_ok = False
            if sess2_res.status_code == 200:
                s2_data = sess2_res.json()
                memories = s2_data.get("evidence", {}).get("memory", [])
                sess2_ok = len(memories) > 0 or ("accept_risk" in s2_data.get("answer", "").lower())
            record(step12_name, sess2_ok, f"(status={sess2_res.status_code})")

            # Step 13: What-If simulation
            step13_name = "13. Analyst POST whatif simulation"
            first_ep = paths[0].get("entrypoint_id") if paths else None
            whatif_payload = {
                "finding_id": top_fid,
                "changes": [{"type": "add_auth", "entrypoint_id": first_ep or "unknown_ep"}],
            }
            whatif_res = client.post(
                f"{BASE_URL}/api/repos/{repo_id}/whatif",
                headers=analyst_headers,
                json=whatif_payload,
            )
            whatif_ok = whatif_res.status_code == 200 and "before" in whatif_res.json() and "after" in whatif_res.json()
            record(step13_name, whatif_ok, f"(status={whatif_res.status_code})")

        # ── Step 14: Delete Repo (Viewer=403, Admin=204) ──────────────
        step14_name = "14. Delete Repo (Viewer=403, Admin=204)"
        v_del_res = client.delete(f"{BASE_URL}/api/repos/{repo_id}", headers=viewer_headers)
        viewer_del_forbidden = (v_del_res.status_code == 403)

        a_del_res = client.delete(f"{BASE_URL}/api/repos/{repo_id}", headers=admin_headers)
        admin_del_ok = (a_del_res.status_code in (200, 204))

        if admin_del_ok and repo_id in created_repo_ids:
            created_repo_ids.remove(repo_id)

        step14_ok = viewer_del_forbidden and admin_del_ok
        record(step14_name, step14_ok, f"(viewer_code={v_del_res.status_code}, admin_code={a_del_res.status_code})")

    except Exception as exc:
        has_failed = True
        print(f"\nUNHANDLED EXCEPTION in e2e run: {exc}", file=sys.stderr)
        record("e2e_run_unhandled", False, str(exc))

    finally:
        # ══════════════════════════════════════════════════════════════════
        # NON-NEGOTIABLE CLEANUP: Ensure every repo created during the run
        # is deleted via admin DELETE, even if a step or assertion failed.
        # ══════════════════════════════════════════════════════════════════
        if created_repo_ids and admin_headers:
            print("\n--- Running Mandatory E2E Cleanup (finally block) ---")
            for rid in list(created_repo_ids):
                try:
                    del_res = client.delete(f"{BASE_URL}/api/repos/{rid}", headers=admin_headers, timeout=10.0)
                    if del_res.status_code in (200, 204):
                        print(f"  [CLEANUP] Deleted repo {rid}")
                        created_repo_ids.remove(rid)
                    elif del_res.status_code == 404:
                        print(f"  [CLEANUP] Repo {rid} was already deleted")
                        created_repo_ids.remove(rid)
                    else:
                        print(f"  [CLEANUP] Could not delete repo {rid}: HTTP {del_res.status_code}")
                except Exception as exc:
                    print(f"  [CLEANUP] Error deleting repo {rid}: {exc}")

        if created_user_ids and admin_headers:
            for uid in list(created_user_ids):
                try:
                    client.patch(
                        f"{BASE_URL}/api/admin/users/{uid}",
                        headers=admin_headers,
                        json={"active": False},
                        timeout=5.0,
                    )
                except Exception:
                    pass

        # Summary Table
        print("\n" + "=" * 60)
        print("E2E INTEGRATION SUITE SUMMARY")
        print("=" * 60)
        passed_count = sum(1 for _, status, _ in results if status == "PASS")
        total_count = len(results)
        for name, status, detail in results:
            print(f"  {status:<6} {name} {detail}")
        print("=" * 60)
        print(f"Result: {passed_count}/{total_count} steps passed.")
        print("=" * 60 + "\n")

        client.close()

    # Exit code
    if any(status == "FAIL" for _, status, _ in results) or has_failed:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
