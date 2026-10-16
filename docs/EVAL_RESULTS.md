# ReachGuard Agent Evaluation Results

**Evaluation Date:** 2026-10-16 10:10:41 UTC  
**Model Name:** `qwen2.5:7b-instruct`  
**Target Repository:** `2f7632cb-9e39-43df-a04e-262547d06c72`  
**Questions Evaluated:** 15  

---

## 1. Summary Metrics

| Metric | Measured Value | Target / Requirement |
| :--- | :---: | :---: |
| **Grounded Responses** | **100.0%** (15/15) | High accuracy (hallucinations rejected) |
| **Verdict Consistency** | **93.3%** (14/15) | 100% (contract labels match graph truth) |
| **Forbidden Phrases Count** | **0** | 0 allowed |

### Median Latency per Mode
- **`deterministic`**: **5.833s** (1 questions)
- **`llm_tools`**: **5.854s** (14 questions)

---

## 2. Detailed Per-Question Results

| # | Finding ID | Package | Question | Mode | Latency (s) | Grounded | Verdict Consistent | Forbidden Phrase |
| :---: | :---: | :---: | :--- | :---: | :---: | :---: | :---: | :---: |
| 1 | `8bc5f7a0c3f7` | `flask` | Is flask in finding 8bc5f7a0c3f7 reachable? | `llm_tools` | 7.47 | ✅ True | ✅ Yes | ✅ None |
| 2 | `8bc5f7a0c3f7` | `flask` | Why is finding 8bc5f7a0c3f7 ranked where it is? | `llm_tools` | 3.70 | ✅ True | ✅ Yes | ✅ None |
| 3 | `8bc5f7a0c3f7` | `flask` | What should I do about finding 8bc5f7a0c3f7? | `llm_tools` | 5.75 | ✅ True | ✅ Yes | ✅ None |
| 4 | `66db7f645972` | `flask` | Is flask in finding 66db7f645972 reachable? | `llm_tools` | 7.55 | ✅ True | ✅ Yes | ✅ None |
| 5 | `66db7f645972` | `flask` | Why is finding 66db7f645972 ranked where it is? | `llm_tools` | 3.88 | ✅ True | ✅ Yes | ✅ None |
| 6 | `66db7f645972` | `flask` | What should I do about finding 66db7f645972? | `llm_tools` | 5.91 | ✅ True | ✅ Yes | ✅ None |
| 7 | `39e21c37a15e` | `flask` | Is flask in finding 39e21c37a15e reachable? | `llm_tools` | 5.88 | ✅ True | ✅ Yes | ✅ None |
| 8 | `39e21c37a15e` | `flask` | Why is finding 39e21c37a15e ranked where it is? | `llm_tools` | 3.75 | ✅ True | ✅ Yes | ✅ None |
| 9 | `39e21c37a15e` | `flask` | What should I do about finding 39e21c37a15e? | `llm_tools` | 5.83 | ✅ True | ✅ Yes | ✅ None |
| 10 | `5b83912307f2` | `flask` | Is flask in finding 5b83912307f2 reachable? | `llm_tools` | 5.93 | ✅ True | ✅ Yes | ✅ None |
| 11 | `5b83912307f2` | `flask` | Why is finding 5b83912307f2 ranked where it is? | `deterministic` | 5.83 | ✅ True | ✅ Yes | ✅ None |
| 12 | `5b83912307f2` | `flask` | What should I do about finding 5b83912307f2? | `llm_tools` | 3.77 | ✅ True | ✅ Yes | ✅ None |
| 13 | `8e89d3435013` | `waitress` | Is waitress in finding 8e89d3435013 reachable? | `llm_tools` | 4.74 | ✅ True | ✅ Yes | ✅ None |
| 14 | `8e89d3435013` | `waitress` | Why is finding 8e89d3435013 ranked where it is? | `llm_tools` | 6.20 | ✅ True | ✅ Yes | ✅ None |
| 15 | `8e89d3435013` | `waitress` | What should I do about finding 8e89d3435013? | `llm_tools` | 9.05 | ✅ True | ❌ No | ✅ None |

---

## 3. Methodology & Evaluation Notes

1. **Test Dataset**: Evaluated against the top 5 findings in the target repository (`2f7632cb-9e39-43df-a04e-262547d06c72`).
2. **Template Coverage**:
   - Reachability query: *"Is `<package>` in finding `<id>` reachable?"*
   - Triage ranking query: *"Why is finding `<id>` ranked where it is?"*
   - Remediation query: *"What should I do about finding `<id>`?"*
3. **Verification Checks**:
   - `grounded`: Enforces that all claimed scores, package versions, and finding IDs exist in graph tool results.
   - `verdict_consistent`: Confirms the stated verdict matches the actual trace verdict without contradictions.
   - `forbidden_detected`: Scans for forbidden certainty claims (*"is safe"*, *"not vulnerable"*, *"no risk"*, *"I fixed"*, etc.).
4. **Data Integrity Guarantee**: All numbers in this document are strictly measured by `scripts/eval_agent.py` directly from the live API responses.
