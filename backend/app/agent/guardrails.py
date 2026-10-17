"""
ReachGuard — Agent Guardrails & Grounding Verification.

Implements Contract Section 5, 6, 10:
Verifies that generated answers are strictly grounded in tool results:
- Extracts 12-char hex finding IDs, package@version / package version mentions,
  numbers following the word 'score', and verdict labels.
- Validates that each finding ID exists in evidence or tool results.
- Validates that each score mentioned matches the score in tool results.
- Validates that verdict labels mentioned near a finding match its verdict without contradiction.
- Rejects forbidden phrases (case-insensitive):
  'is safe', 'not vulnerable', 'no risk', 'not exploitable', 'safe to ignore',
  'I have applied', 'I fixed', 'patched it', 'I upgraded'.
- If any check fails, returns grounded=False with the exact list of problems.
- If no IDs are mentioned (generic answer), grounded is True, but adds a warning
  only when the user message referenced a finding.
"""

from __future__ import annotations

import re
from typing import Any

from app.agent.planner import extract_finding_ids, extract_referenced_finding

FORBIDDEN_PHRASES: list[str] = [
    "is safe",
    "not vulnerable",
    "no risk",
    "not exploitable",
    "safe to ignore",
    "i have applied",
    "i fixed",
    "patched it",
    "i upgraded",
]

# Pattern for score extraction: numbers following the word "score"
# Matches: "score: 85", "score 85", "score of 85", "score is 85", "score = 85", "score was 85", "score: 85/100"
SCORE_PATTERN = re.compile(
    r"\bscore(?:\s+(?:is|was|of|equals?))?\s*[:=]?\s*(\d{1,3})(?:/100)?\b",
    re.IGNORECASE,
)

# Pattern for package@version and "package version"
# Matches: "requests@2.25.0", "requests 2.25.0", "urllib3 v1.26.4"
PACKAGE_VER_PATTERN = re.compile(
    r"\b([a-zA-Z0-9_\-\.]+)(?:@|\s+v?)([0-9]+\.[0-9]+(?:\.[0-9a-zA-Z_\-]+)?)\b"
)


def _get_surrounding_sentence(text: str, start: int, end: int, window: int = 150) -> str:
    """Extract the sentence or local window containing a match."""
    pre = text[:start]
    post = text[end:]

    pre_delim = max(pre.rfind("."), pre.rfind("\n"), pre.rfind("!"), pre.rfind("?"))
    post_delim_candidates = [post.find("."), post.find("\n"), post.find("!"), post.find("?")]
    valid_post_delims = [d for d in post_delim_candidates if d != -1]
    post_delim = min(valid_post_delims) if valid_post_delims else len(post)

    sent_start = pre_delim + 1 if pre_delim != -1 else max(0, start - window)
    sent_end = end + post_delim + 1 if valid_post_delims else min(len(text), end + window)
    return text[sent_start:sent_end]


def _collect_ground_truth(
    evidence: dict[str, Any] | None,
    tool_results: list[dict[str, Any]] | None,
) -> tuple[dict[str, dict[str, Any]], dict[str, str], set[str], set[str]]:
    """Gather all ground-truth findings, scores, verdicts, packages, modules, and clusters from evidence and tool outputs.

    Returns:
        (known_findings, known_packages, known_modules, known_clusters)
    """
    known_findings: dict[str, dict[str, Any]] = {}
    known_packages: dict[str, str] = {}
    known_modules: set[str] = set()
    known_clusters: set[str] = set()

    def ingest_finding_dict(d: dict[str, Any]) -> None:
        candidate_ids = []
        if d.get("finding_id"):
            candidate_ids.append(d["finding_id"])
        if d.get("id"):
            candidate_ids.append(d["id"])

        for fid in candidate_ids:
            if fid and isinstance(fid, str):
                fid_clean = fid.lower()
                if fid_clean not in known_findings:
                    known_findings[fid_clean] = {"scores": set()}

                for field_name in ("verdict", "package", "version", "severity", "vuln_id"):
                    val = d.get(field_name)
                    if val is not None:
                        known_findings[fid_clean][field_name] = val

                if "score" in d and d["score"] is not None:
                    known_findings[fid_clean]["score"] = d["score"]
                    try:
                        known_findings[fid_clean]["scores"].add(int(d["score"]))
                    except (ValueError, TypeError):
                        pass

                # Also check score_breakdown if present
                s_bd = d.get("score_breakdown")
                if isinstance(s_bd, dict) and "score" in s_bd and s_bd["score"] is not None:
                    known_findings[fid_clean]["score"] = s_bd["score"]
                    try:
                        known_findings[fid_clean]["scores"].add(int(s_bd["score"]))
                    except (ValueError, TypeError):
                        pass

                pkg = d.get("package")
                ver = d.get("version")
                if pkg and ver and isinstance(pkg, str) and isinstance(ver, str):
                    known_packages[pkg.lower()] = ver

    def recurse_ingest(item: Any) -> None:
        if isinstance(item, dict):
            # Clusters
            if item.get("cluster_id"):
                cid_str = str(item["cluster_id"]).lower()
                known_clusters.add(cid_str)
                known_clusters.add(cid_str.replace("-", "_"))

            if "clusters" in item and isinstance(item["clusters"], list):
                for c in item["clusters"]:
                    if isinstance(c, dict):
                        if c.get("cluster_id"):
                            c_id = str(c["cluster_id"]).lower()
                            known_clusters.add(c_id)
                            known_clusters.add(c_id.replace("-", "_"))
                        if "modules" in c and isinstance(c["modules"], list):
                            for m in c["modules"]:
                                if m and isinstance(m, str):
                                    known_modules.add(m.lower())

            # Modules
            if "modules" in item and isinstance(item["modules"], list):
                for m in item["modules"]:
                    if isinstance(m, dict) and m.get("module"):
                        known_modules.add(str(m["module"]).lower())
                    elif isinstance(m, str):
                        known_modules.add(m.lower())

            if "module" in item and item["module"] and isinstance(item["module"], str):
                known_modules.add(item["module"].lower())

            if "module_id" in item and item["module_id"] and isinstance(item["module_id"], str):
                known_modules.add(item["module_id"].lower())

            # Path nodes in traces
            if "nodes" in item and isinstance(item["nodes"], list):
                for n in item["nodes"]:
                    if isinstance(n, dict):
                        if n.get("label") == "Module":
                            if n.get("id"):
                                known_modules.add(str(n["id"]).lower())
                            if n.get("name"):
                                known_modules.add(str(n["name"]).lower())

            # Check if this dict itself is a finding, trace, decision, or investigation
            if "id" in item or "finding_id" in item:
                ingest_finding_dict(item)

            # Ingest child findings if list_findings structure
            if "findings" in item and isinstance(item["findings"], list):
                for f in item["findings"]:
                    if isinstance(f, dict):
                        ingest_finding_dict(f)

            # Ingest traces if evidence structure
            if "traces" in item and isinstance(item["traces"], list):
                for t in item["traces"]:
                    if isinstance(t, dict):
                        ingest_finding_dict(t)

            # Ingest decisions and investigations from recall memory
            if "decisions" in item and isinstance(item["decisions"], list):
                for dec in item["decisions"]:
                    if isinstance(dec, dict):
                        ingest_finding_dict(dec)

            if "investigations" in item and isinstance(item["investigations"], list):
                for inv in item["investigations"]:
                    if isinstance(inv, dict):
                        ingest_finding_dict(inv)

            if "hits" in item and isinstance(item["hits"], list):
                for hit in item["hits"]:
                    if isinstance(hit, dict):
                        ingest_finding_dict(hit)
                        pkg_hit = hit.get("package_name") or hit.get("pattern_name")
                        if pkg_hit and isinstance(pkg_hit, str):
                            known_packages[pkg_hit.lower()] = ""

            # Recurse into values if tool dicts like {"trace_path": {...}}
            for v in item.values():
                if isinstance(v, (dict, list)):
                    recurse_ingest(v)

        elif isinstance(item, list):
            for sub in item:
                recurse_ingest(sub)

    if evidence:
        recurse_ingest(evidence)
    if tool_results:
        recurse_ingest(tool_results)

    return known_findings, known_packages, known_modules, known_clusters


MODULE_STOPWORDS = {
    "this", "that", "these", "those", "the", "a", "an", "is", "are", "was", "were",
    "each", "every", "all", "both", "either", "neither", "one", "two", "three", "ten",
    "critical", "central", "important", "python", "in", "to", "of", "and", "or",
    "for", "with", "no", "none", "by", "from", "on", "as", "at", "not", "be",
    "has", "have", "had", "can", "could", "should", "would", "which", "what",
    "where", "when", "who", "why", "how", "top", "such", "other", "some", "many",
    "several", "first", "last", "any", "same", "different", "new", "old", "s",
    "their", "there", "here", "its", "it", "they", "them", "we", "us", "you",
    "score", "scores", "path", "paths", "finding", "findings", "repo", "repository",
    "algorithm", "fallback", "pagerank", "centrality", "reach_centrality", "owner", "owners",
    "listed", "below", "following", "above", "highest", "lowest", "most", "least",
}

CLUSTER_ID_PATTERN = re.compile(r"\bcluster[_\-](\d+|[a-zA-Z0-9]+)\b", re.IGNORECASE)


def extract_mentioned_clusters(text: str) -> list[str]:
    """Extract cluster identifiers like cluster_1, cluster-2 from text."""
    seen = set()
    results = []
    for m in CLUSTER_ID_PATTERN.finditer(text):
        cid = m.group(0).lower().replace("-", "_")
        if cid not in seen:
            seen.add(cid)
            results.append(cid)
    return results


def extract_mentioned_modules(text: str) -> list[str]:
    """Extract module names mentioned in text."""
    candidates: list[str] = []

    # 1. Matches: "module <name>", "module: <name>", "module '<name>'", etc.
    module_prefix_re = re.compile(
        r"\bmodule\s*[:=]?\s*[`'\"]?([a-zA-Z_][a-zA-Z0-9_\.\-]*)[`'\"]?",
        re.IGNORECASE,
    )
    for m in module_prefix_re.finditer(text):
        cand = m.group(1).strip("`'\".,;:()")
        if cand and cand.lower() not in MODULE_STOPWORDS:
            candidates.append(cand)

    # 2. Matches: "<name> module" e.g. "made_up_module module", "app.views module"
    suffix_re = re.compile(
        r"[`'\"]?([a-zA-Z_][a-zA-Z0-9_\.\-]+)[`'\"]?\s+modules?\b",
        re.IGNORECASE,
    )
    for m in suffix_re.finditer(text):
        cand = m.group(1).strip("`'\".,;:()")
        if cand and cand.lower() not in MODULE_STOPWORDS:
            candidates.append(cand)

    # 3. Matches in bullet lists or comma lists under "Critical modules:" or "Modules:"
    list_header_re = re.compile(
        r"(?:critical\s+modules?|central\s+modules?|modules?)\s*[:=]\s*([^\n\.]+)",
        re.IGNORECASE,
    )
    for m in list_header_re.finditer(text):
        items = re.split(r"[,;]|\band\b", m.group(1))
        for item in items:
            cand = item.strip(" `'\":-*()\n\t")
            first_tok = cand.split()[0] if cand.split() else ""
            clean_tok = first_tok.strip("`'\".,;:()")
            if clean_tok and clean_tok.lower() not in MODULE_STOPWORDS:
                candidates.append(clean_tok)

    # 4. Dotted module paths: e.g. "app.views", "good.vulpy"
    dotted_re = re.compile(r"\b([a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z0-9_\-]+)+)\b")
    for m in dotted_re.finditer(text):
        cand = m.group(1).strip("`'\".,;:()")
        lower = cand.lower()
        # Skip emails and common domain or file extensions
        preceding = text[max(0, m.start() - 20) : m.start()]
        if "@" in preceding:
            continue
        if not any(
            lower.endswith(ext)
            for ext in (".com", ".org", ".net", ".io", ".internal", ".local", ".dev", ".edu", ".gov", ".json", ".md", ".txt", ".html")
        ):
            candidates.append(cand)

    # 5. Bullet list items: "* good.vulpy", "- app.views"
    bullet_re = re.compile(r"^\s*[\*\-]\s*[`'\"]?([a-zA-Z_][a-zA-Z0-9_\.\-]+)[`'\"]?", re.MULTILINE)
    for m in bullet_re.finditer(text):
        cand = m.group(1).strip("`'\".,;:()")
        if cand and cand.lower() not in MODULE_STOPWORDS and not cand.startswith("http"):
            candidates.append(cand)

    # Deduplicate preserving order
    seen = set()
    result = []
    for c in candidates:
        if c.lower() not in seen:
            seen.add(c.lower())
            result.append(c)
    return result


def check_grounding(
    answer_text: str,
    evidence: dict[str, Any] | None = None,
    tool_results: list[dict[str, Any]] | None = None,
    user_message: str | None = None,
    repo_id: str | None = None,
) -> dict[str, Any]:
    """Verify that answer_text is strictly grounded in evidence and tool results.

    Returns:
        {"grounded": bool, "warnings": [str]}
    """
    warnings: list[str] = []
    grounded = True
    lower_answer = answer_text.lower()

    # ─────────────────────────────────────────────────────────────
    # 1. Forbidden phrases (case-insensitive)
    # ─────────────────────────────────────────────────────────────
    for phrase in FORBIDDEN_PHRASES:
        if phrase in lower_answer:
            warnings.append(
                f"Forbidden phrase detected: '{phrase}'. Never state a package is safe or that changes were applied."
            )
            grounded = False

    known_findings, known_packages, known_modules, known_clusters = _collect_ground_truth(evidence, tool_results)

    # Context explicitly referenced in user's prompt is valid conversational context
    if user_message:
        for ufid in extract_finding_ids(user_message):
            if ufid.lower() not in known_findings:
                known_findings[ufid.lower()] = {"scores": set()}
        for umod in extract_mentioned_modules(user_message):
            known_modules.add(umod.lower())
        for ucid in extract_mentioned_clusters(user_message):
            known_clusters.add(ucid.lower())

    # ─────────────────────────────────────────────────────────────
    # 2. Extract 12-char hex finding IDs
    # ─────────────────────────────────────────────────────────────
    mentioned_ids = extract_finding_ids(answer_text)

    # Each finding ID must exist in evidence or tool results
    for mid in mentioned_ids:
        if mid not in known_findings:
            warnings.append(f"Made-up or unknown finding ID '{mid}' is not in evidence or tool results.")
            grounded = False

    # ─────────────────────────────────────────────────────────────
    # 2b. Extract and validate cluster IDs
    # ─────────────────────────────────────────────────────────────
    mentioned_clusters = extract_mentioned_clusters(answer_text)
    for cid in mentioned_clusters:
        if cid.lower() not in known_clusters and cid.lower().replace("-", "_") not in known_clusters:
            warnings.append(f"Made-up or unknown cluster ID '{cid}' is not in evidence or tool results.")
            grounded = False

    # ─────────────────────────────────────────────────────────────
    # 2c. Extract and validate module names
    # ─────────────────────────────────────────────────────────────
    mentioned_modules = extract_mentioned_modules(answer_text)
    for mod in mentioned_modules:
        mod_l = mod.lower()
        if mod_l not in known_modules and not any(km.endswith("." + mod_l) for km in known_modules):
            warnings.append(f"Made-up or unknown module '{mod}' is not in evidence or tool results.")
            grounded = False

    # ─────────────────────────────────────────────────────────────
    # 3. Extract numbers following the word "score"
    # ─────────────────────────────────────────────────────────────
    for match in SCORE_PATTERN.finditer(answer_text):
        try:
            score_val = int(match.group(1))
        except ValueError:
            continue

        sent = _get_surrounding_sentence(answer_text, match.start(), match.end())
        sent_fids = extract_finding_ids(sent)

        if sent_fids:
            # Score is associated with specific finding(s) in the sentence
            for fid in sent_fids:
                if fid in known_findings:
                    expected_scores = known_findings[fid].get("scores") or {
                        int(known_findings[fid]["score"])
                        for _ in (1,)
                        if known_findings[fid].get("score") is not None
                    }
                    if expected_scores and score_val not in expected_scores:
                        warnings.append(
                            f"Mentioned score {score_val} does not match expected score {min(expected_scores)} for finding {fid}."
                        )
                        grounded = False
        elif len(mentioned_ids) == 1:
            # Single finding mentioned in the entire answer
            fid = mentioned_ids[0]
            if fid in known_findings:
                expected_scores = known_findings[fid].get("scores") or {
                    int(known_findings[fid]["score"])
                    for _ in (1,)
                    if known_findings[fid].get("score") is not None
                }
                if expected_scores and score_val not in expected_scores:
                    warnings.append(
                        f"Mentioned score {score_val} does not match expected score {min(expected_scores)} for finding {fid}."
                    )
                    grounded = False
        else:
            # Check against any known score in tool results
            valid_scores = {
                s
                for info in known_findings.values()
                for s in info.get("scores", set())
            } or {
                int(info["score"])
                for info in known_findings.values()
                if info.get("score") is not None
            }
            if valid_scores and score_val not in valid_scores:
                warnings.append(
                    f"Mentioned score {score_val} does not match any finding score in tool results ({sorted(valid_scores)})."
                )
                grounded = False

    # ─────────────────────────────────────────────────────────────
    # 4. Extract package@version or "package version" mentions
    # ─────────────────────────────────────────────────────────────
    for match in PACKAGE_VER_PATTERN.finditer(answer_text):
        pkg_name = match.group(1).lower()
        ver_str = match.group(2)

        # Only validate packages known from tool results/evidence
        if pkg_name in known_packages:
            expected_ver = known_packages[pkg_name]
            if ver_str != expected_ver:
                warnings.append(
                    f"Package '{pkg_name}' version '{ver_str}' does not match expected version '{expected_ver}' in tool results."
                )
                grounded = False

        # If mentioned in same sentence as a finding, verify package matches that finding
        sent = _get_surrounding_sentence(answer_text, match.start(), match.end())
        sent_fids = extract_finding_ids(sent)
        for fid in sent_fids:
            if fid in known_findings:
                expected_pkg = known_findings[fid].get("package")
                if (
                    expected_pkg
                    and pkg_name != expected_pkg.lower()
                    and pkg_name in known_packages
                    and expected_pkg.lower() in known_packages
                ):
                    warnings.append(
                        f"Package '{pkg_name}' mentioned for finding {fid} does not match expected package '{expected_pkg}'."
                    )
                    grounded = False

    # ─────────────────────────────────────────────────────────────
    # 5. Extract verdict labels and verify consistency near finding
    # ─────────────────────────────────────────────────────────────
    for mid in mentioned_ids:
        if mid in known_findings:
            expected_verdict = known_findings[mid].get("verdict")
            if expected_verdict:
                # Find all occurrences of mid in the answer and inspect the surrounding sentence
                fid_pattern = re.compile(rf"\b{re.escape(mid)}\b", re.IGNORECASE)
                for m in fid_pattern.finditer(answer_text):
                    sent = _get_surrounding_sentence(answer_text, m.start(), m.end())
                    sent_lower = sent.lower()

                    # Extract verdict labels present in this sentence
                    labels_in_sent: list[tuple[str, str]] = []
                    if "reachable in model" in sent_lower:
                        labels_in_sent.append(("Reachable in model", "reachable_in_model"))
                    if "no path found in model" in sent_lower:
                        labels_in_sent.append(("No path found in model", "no_path_found"))
                    elif "no path found" in sent_lower:
                        labels_in_sent.append(("No path found", "no_path_found"))
                    if "verdict: unknown" in sent_lower or "verdict unknown" in sent_lower:
                        labels_in_sent.append(("Unknown", "unknown"))

                    for raw_label, norm_label in labels_in_sent:
                        if norm_label != expected_verdict:
                            warnings.append(
                                f"Contradictory verdict label '{raw_label}' mentioned for finding {mid} (expected '{expected_verdict}')."
                            )
                            grounded = False

    # ─────────────────────────────────────────────────────────────
    # 6. Generic answer check: no IDs mentioned at all
    # ─────────────────────────────────────────────────────────────
    if not mentioned_ids and user_message:
        referenced_id = extract_referenced_finding(repo_id or "", user_message)
        user_hex_ids = extract_finding_ids(user_message)
        target_id = referenced_id or (user_hex_ids[0] if user_hex_ids else None)

        if target_id:
            warnings.append(
                f"User message referenced finding '{target_id}', but answer did not cite any finding ID."
            )

    return {
        "grounded": grounded,
        "warnings": warnings,
    }
