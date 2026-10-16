"""
ReachGuard — Agent Chat API Router.

Implements Contract Section 7:
POST /api/repos/{repo_id}/agent/chat
"""

from __future__ import annotations

import logging
import uuid
from collections import OrderedDict
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.agent.loop import AgentResult, run_agent
from app.agent.planner import extract_finding_ids
from app.agent.tools import ToolContext
from app.agent.tools import save_investigation as save_investigation_tool
from app.api.common import check_repo_ready
from app.deps import get_current_user

logger = logging.getLogger(__name__)

# ── Non-persistent in-memory conversation history LRU ─────────
# Documented: in-memory cache of up to 200 sessions, capped at 12 messages each.
# Non-persistent; persistent memory lives in the graph only.
_MAX_SESSIONS = 200
_MAX_MESSAGES_PER_SESSION = 12
_session_histories: OrderedDict[str, list[dict[str, str]]] = OrderedDict()


def _get_session_history(session_id: str) -> list[dict[str, str]]:
    """Retrieve message history for session_id and update LRU position."""
    if session_id in _session_histories:
        _session_histories.move_to_end(session_id)
        return list(_session_histories[session_id])
    return []


def _append_session_history(session_id: str, user_msg: str, assistant_msg: str) -> None:
    """Store user and assistant turns in session LRU cache."""
    history = _session_histories.get(session_id, [])
    history.append({"role": "user", "content": user_msg})
    history.append({"role": "assistant", "content": assistant_msg})
    _session_histories[session_id] = history[-_MAX_MESSAGES_PER_SESSION:]
    _session_histories.move_to_end(session_id)
    while len(_session_histories) > _MAX_SESSIONS:
        _session_histories.popitem(last=False)


# ── Rate limiter key generator (per user) ──────────────────────


def _user_rate_limit_key(request: Request) -> str:
    """Extract authenticated user identifier for rate limiting; falls back to IP."""
    auth_header = request.headers.get("authorization")
    if auth_header and auth_header.lower().startswith("bearer "):
        token = auth_header[7:].strip()
        try:
            from app.auth.security import decode_access_token

            payload = decode_access_token(token)
            sub = payload.get("sub")
            if sub:
                return f"user:{sub}"
        except Exception as exc:  # noqa: BLE001
            logger.debug("Could not decode token for rate limiting: %s", exc)
    return get_remote_address(request)


# Use the limiter attached to app.state if available, or create one with user key func
limiter = Limiter(key_func=_user_rate_limit_key)

agent_router = APIRouter(prefix="/api/repos/{repo_id}/agent", tags=["agent"])


# ── Schemas ───────────────────────────────────────────────────


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000, description="User question (1-2000 chars)")
    session_id: str | None = Field(default=None, description="Optional conversation session UUID")
    save: bool = Field(default=False, description="Persist investigation if single finding (analyst/admin only)")


class ToolCallSummary(BaseModel):
    name: str
    args: dict[str, Any]
    ok: bool
    summary: str


class EvidenceSummary(BaseModel):
    findings: list[dict[str, Any]]
    traces: list[dict[str, Any]]
    memory: list[dict[str, Any]]


class ChatResponse(BaseModel):
    session_id: str
    answer: str
    mode: str
    tool_calls: list[dict[str, Any]]
    evidence: dict[str, Any]
    grounded: bool
    warnings: list[str]


# ── Endpoint ──────────────────────────────────────────────────


@agent_router.post("/chat", response_model=ChatResponse)
@limiter.limit("20/minute", key_func=_user_rate_limit_key)
def chat(
    request: Request,
    repo_id: str,
    req: ChatRequest,
    current_user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any] | JSONResponse:
    """Chat with the ReachGuard AI triage agent per Contract Section 7.

    - Accessible to viewer, analyst, and admin.
    - save=true is honored only for analyst and admin; 403 for viewers.
    - Rate limited to 20 requests per minute per user.
    """
    # 1. Validate message length
    msg_stripped = req.message.strip()
    if not msg_stripped or len(req.message) > 2000:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Message must be between 1 and 2000 characters",
        )

    # 2. Validate repo exists and is ready (raises 404 or 409)
    check_repo_ready(repo_id)

    # 3. RBAC on save=true: viewers cannot save investigations
    user_role = current_user.get("role", "viewer")
    if req.save and user_role not in ("analyst", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only analysts and admins can save investigations",
        )

    # 4. Generate or maintain session_id
    session_id = req.session_id.strip() if req.session_id and req.session_id.strip() else str(uuid.uuid4())

    # 5. Retrieve non-persistent in-memory session history
    history = _get_session_history(session_id)

    try:
        ctx = ToolContext(
            repo_id=repo_id,
            user_role=user_role,
            user_email=current_user.get("email", ""),
            save_allowed=req.save and user_role in ("analyst", "admin"),
            session_id=session_id,
        )

        agent_result: AgentResult = run_agent(
            ctx=ctx,
            message=req.message,
            history=history,
        )

        # 6. Save investigation if requested and answer concerns exactly one finding
        if req.save and user_role in ("analyst", "admin"):
            mentioned_fids = extract_finding_ids(agent_result.answer)
            trace_fids = list(
                dict.fromkeys([
                    t["finding_id"]
                    for t in agent_result.evidence.get("traces", [])
                    if isinstance(t, dict) and "finding_id" in t
                ])
            )

            single_finding_id: str | None = None
            if len(mentioned_fids) == 1:
                single_finding_id = mentioned_fids[0]
            elif len(mentioned_fids) == 0 and len(trace_fids) == 1:
                single_finding_id = trace_fids[0]

            if single_finding_id:
                summary_text = agent_result.answer[:500]
                save_res = save_investigation_tool(
                    ctx,
                    finding_id=single_finding_id,
                    summary=summary_text,
                )
                if save_res.get("ok"):
                    agent_result.tool_calls.append({
                        "name": "save_investigation",
                        "args": {"finding_id": single_finding_id, "summary": summary_text},
                        "ok": True,
                        "summary": f"save_investigation({single_finding_id}): saved {save_res.get('investigation_id', '')}",
                    })

        # 7. Update in-memory session history
        _append_session_history(session_id, req.message, agent_result.answer)

        # 8. Return contract response shape
        return {
            "session_id": session_id,
            "answer": agent_result.answer,
            "mode": agent_result.mode,
            "tool_calls": agent_result.tool_calls,
            "evidence": agent_result.evidence,
            "grounded": agent_result.grounded,
            "warnings": agent_result.warnings,
        }

    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected error in agent chat endpoint")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"error": {"code": 500, "message": "Internal server error"}},
        )
