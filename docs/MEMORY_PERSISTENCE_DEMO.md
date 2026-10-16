# C10: ReachGuard Memory Behavior & Graph Persistence Demo

**Verification Date:** 2026-10-16 13:05:23 UTC  
**Target Finding:** `8bc5f7a0c3f7` (Package: `flask@2.0.1`, Repo: `2f7632cb-9e39-43df-a04e-262547d06c72`)  
**Design Principle:** *"The graph decides, the model explains; memory lives in the graph, not in ephemeral process state."*

---

## 1. Executive Summary

![C10 Memory Persistence Demo Slide](/Users/patelkrina/.gemini/antigravity-ide/brain/c2c2a58a-536b-4409-8ad2-63a6a4f1ccdc/c10_memory_persistence_deck_1792156135229.jpg)

This verification confirms the core persistence architecture of ReachGuard per Contract Section 7 & 10:
1. **Zero State in App Memory:** Conversation history in FastAPI process memory is an ephemeral LRU cache. All persistent memory (past investigations, triage notes, risk decisions) lives exclusively in the FalkorDB graph.
2. **Persistence Across Complete Process Restart:** After an analyst investigated finding `8bc5f7a0c3f7` with `save=true` and recorded an `accept_risk` decision (approved by admin), the uvicorn server process was killed (`SIGINT`) and restarted with completely fresh process state.
3. **Graph Memory Recall in a Fresh Session:** A brand-new session (`session_id: fd821365-c46d-4885-81b5-66463a073c66`) asked *"Do we know anything about finding 8bc5f7a0c3f7?"*.
4. **Verified Result:**
   - **Mode:** `llm_tools`
   - **Grounded:** `True`
   - **`evidence.memory`:** Non-empty (contains the full graph decision and investigation chain).
   - **Answer Output:** Correctly cites that the risk was accepted, who approved it (`admin@reachguard.io`), and the specific compensating control reason (*"isolated behind a VPC security group without public ingress"*).

---

## 2. Step-by-Step Execution Trace

### Step 1: Analyst Chat & Risk Decision
- **User:** `analyst@reachguard.io` (Role: `analyst`)
- **Query:** `"Is flask in finding 8bc5f7a0c3f7 reachable?"` with `save=true`
- **Result:** Agent confirmed reachable (`reachable_in_model`, 18 entrypoints) and saved an `Investigation` node attached to `(:Finding {id: "8bc5f7a0c3f7"})` in FalkorDB.
- **Decision Created:**
  ```json
  POST /api/repos/2f7632cb-9e39-43df-a04e-262547d06c72/findings/8bc5f7a0c3f7/decisions
  {
    "type": "accept_risk",
    "reason": "Internal staging service only; network isolated behind VPC security group without public ingress"
  }
  ```
- **Decision Node Created:** ID `964651f8b5e3`, initial status: `pending`.

### Step 2: Admin Approval
- **User:** `admin@reachguard.io` (Role: `admin`)
- **Endpoint:** `POST /api/repos/2f7632cb-9e39-43df-a04e-262547d06c72/decisions/964651f8b5e3/approve`
- **Graph Update:** `(:Decision {id: "964651f8b5e3"})` status updated to `approved`, `approved_by: "admin@reachguard.io"`.

### Step 3: Hard Server Restart
- **Action:** Process killed via `SIGINT` (PID `1959` terminated).
- **Process Memory Wiped:** All FastAPI in-memory session dictionaries and cache entries were destroyed.
- **Restart:** New uvicorn instance launched (PID `2103`).

### Step 4: Fresh Session Memory Inquiry
- **User:** `analyst@reachguard.io`
- **Session:** Brand-new UUID `fd821365-c46d-4885-81b5-66463a073c66`
- **Query:** `"Do we know anything about finding 8bc5f7a0c3f7?"`

---

## 3. Measured Response & Graph Evidence

### Agent Answer
```text
The finding 8bc5f7a0c3f7 indicates that Flask is reachable in the model. The exact entrypoints are:

* GET /iframe-injection
* GET /idor/profile
* POST /idor/login

These entrypoints are reachable due to the "HANDLED_BY" and "USES" edges in the graph. The risk score for this finding is 92.

This is not proof of safety, but rather indicates that there are public entrypoints connecting to the Flask package. The decision to accept the risk was made by admin@reachguard.io, who stated that the service is only used internally and is isolated behind a VPC security group without public ingress.
```

### `evidence.memory` Payload
```json
[
  {
    "ok": true,
    "investigations": [
      {
        "id": "ce1cbc917c05",
        "created_at": "2026-10-16T12:59:02.604731+00:00",
        "by": "analyst@reachguard.io",
        "verdict": "reachable_in_model",
        "score": 92,
        "summary": "The finding 8bc5f7a0c3f7 indicates that Flask is reachable in the model...",
        "finding_id": "8bc5f7a0c3f7"
      }
    ],
    "decisions": [
      {
        "id": "964651f8b5e3",
        "type": "accept_risk",
        "reason": "Internal staging service only; network isolated behind VPC security group without public ingress",
        "by": "analyst@reachguard.io",
        "status": "approved",
        "approved_by": "admin@reachguard.io",
        "created_at": "2026-10-16T12:59:02.631592+00:00",
        "finding_id": "8bc5f7a0c3f7"
      }
    ]
  }
]
```

---

## 4. Key Takeaways for the Pitch Deck (Member-4)

> *"In traditional AI security assistants, context is lost the moment a session expires or a server restarts. In ReachGuard, memory is anchored directly in the graph. Even after a complete cold restart of the application server, a new analyst querying finding `8bc5f7a0c3f7` is instantly informed of the prior approved risk acceptance and the exact architectural reasoning behind it."*
