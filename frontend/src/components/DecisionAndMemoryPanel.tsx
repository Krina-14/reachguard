import React, { useState } from "react";
import { apiFetch } from "../api/client";
import { useCan } from "../auth/useCan";
import type { Decision, Investigation, DecisionType } from "../api/types";

interface DecisionAndMemoryPanelProps {
  repoId: string;
  findingId: string;
  decisions: Decision[];
  investigations: Investigation[];
  onUpdated: () => void;
}

export const DecisionAndMemoryPanel: React.FC<DecisionAndMemoryPanelProps> = ({
  repoId,
  findingId,
  decisions,
  investigations,
  onUpdated,
}) => {
  const { canSave, canApprove } = useCan();

  // Create decision form state
  const [decisionType, setDecisionType] = useState<DecisionType>("fix_planned");
  const [reason, setReason] = useState("");
  const [expiresAt, setExpiresAt] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [formSuccess, setFormSuccess] = useState<string | null>(null);

  // Admin approval action loading states
  const [processingDecisionId, setProcessingDecisionId] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setFormError(null);
    setFormSuccess(null);

    if (reason.trim().length < 10) {
      setFormError("Reason must be at least 10 characters long.");
      return;
    }

    setIsSubmitting(true);
    try {
      await apiFetch<Decision>(
        `/api/repos/${repoId}/findings/${findingId}/decisions`,
        {
          method: "POST",
          body: JSON.stringify({
            type: decisionType,
            reason: reason.trim(),
            expires_at: expiresAt ? new Date(expiresAt).toISOString() : null,
          }),
        }
      );

      setReason("");
      setExpiresAt("");
      setFormSuccess(
        decisionType === "accept_risk"
          ? "Decision created: Pending admin approval"
          : "Decision created successfully"
      );
      onUpdated();
    } catch (err: unknown) {
      setFormError(
        err instanceof Error ? err.message : "Failed to record decision"
      );
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleApprove = async (decisionId: string) => {
    setProcessingDecisionId(decisionId);
    try {
      await apiFetch(`/api/repos/${repoId}/decisions/${decisionId}/approve`, {
        method: "POST",
      });
      onUpdated();
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : "Failed to approve decision");
    } finally {
      setProcessingDecisionId(null);
    }
  };

  const handleReject = async (decisionId: string) => {
    setProcessingDecisionId(decisionId);
    try {
      await apiFetch(`/api/repos/${repoId}/decisions/${decisionId}/reject`, {
        method: "POST",
      });
      onUpdated();
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : "Failed to reject decision");
    } finally {
      setProcessingDecisionId(null);
    }
  };

  const formatDecisionType = (type: DecisionType) => {
    switch (type) {
      case "accept_risk":
        return "Accept Risk";
      case "fix_planned":
        return "Fix Planned";
      case "false_positive":
        return "False Positive";
      case "fixed":
        return "Fixed";
      default:
        return type;
    }
  };

  return (
    <div className="space-y-6">
      {/* ════════════════════════════════════════════════════════════════
          DECISION CREATION FORM (Analyst & Admin)
          ════════════════════════════════════════════════════════════════ */}
      {canSave ? (
        <div className="bg-bg-surface border border-border rounded-xl p-5 shadow-sm space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold uppercase tracking-wider text-white flex items-center gap-2">
              <svg className="w-4 h-4 text-accent" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
                <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
              </svg>
              Record Decision
            </h3>
            <span className="text-xs text-gray-400">Analyst / Admin Action</span>
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <label className="block text-xs font-medium text-gray-300 mb-1">
                  Decision Type
                </label>
                <select
                  value={decisionType}
                  onChange={(e) => setDecisionType(e.target.value as DecisionType)}
                  className="w-full bg-bg-card border border-border rounded-lg px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-1 focus:ring-accent"
                >
                  <option value="fix_planned">Fix Planned</option>
                  <option value="accept_risk">
                    Accept Risk (Requires Admin Approval)
                  </option>
                  <option value="false_positive">False Positive</option>
                  <option value="fixed">Fixed</option>
                </select>
                {decisionType === "accept_risk" && (
                  <p className="text-[11px] text-amber-400 mt-1">
                    Accepting risk starts in <strong>Pending</strong> state until an Admin approves it.
                  </p>
                )}
              </div>

              <div>
                <label className="block text-xs font-medium text-gray-300 mb-1">
                  Expiry Date (Optional)
                </label>
                <input
                  type="date"
                  value={expiresAt}
                  onChange={(e) => setExpiresAt(e.target.value)}
                  className="w-full bg-bg-card border border-border rounded-lg px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-1 focus:ring-accent"
                />
              </div>
            </div>

            <div>
              <div className="flex items-center justify-between mb-1">
                <label className="block text-xs font-medium text-gray-300">
                  Reason / Justification
                </label>
                <span
                  className={`text-[11px] font-mono ${
                    reason.trim().length >= 10 ? "text-emerald-400" : "text-gray-500"
                  }`}
                >
                  {reason.trim().length} / min 10 chars
                </span>
              </div>
              <textarea
                rows={3}
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder="Explain the security rationale, mitigation, or remediation plan (minimum 10 characters)..."
                className="w-full bg-bg-card border border-border rounded-lg px-3 py-2 text-sm text-gray-200 placeholder-gray-500 focus:outline-none focus:ring-1 focus:ring-accent"
              />
            </div>

            {formError && (
              <div className="p-3 rounded-lg bg-red-500/15 border border-red-500/30 text-red-400 text-xs">
                {formError}
              </div>
            )}

            {formSuccess && (
              <div className="p-3 rounded-lg bg-emerald-500/15 border border-emerald-500/30 text-emerald-400 text-xs">
                {formSuccess}
              </div>
            )}

            <div className="flex justify-end">
              <button
                type="submit"
                disabled={isSubmitting || reason.trim().length < 10}
                className="px-4 py-2 bg-accent hover:bg-accent-hover disabled:bg-gray-700 disabled:cursor-not-allowed text-white text-xs font-semibold rounded-lg shadow-sm transition-colors"
              >
                {isSubmitting ? "Submitting..." : "Save Decision"}
              </button>
            </div>
          </form>
        </div>
      ) : (
        <div className="p-4 rounded-xl border border-border bg-bg-surface/50 text-xs text-gray-400">
          Sign in as an <strong>Analyst</strong> or <strong>Admin</strong> to record risk decisions.
        </div>
      )}

      {/* ════════════════════════════════════════════════════════════════
          DECISION HISTORY & APPROVALS
          ════════════════════════════════════════════════════════════════ */}
      <div className="bg-bg-surface border border-border rounded-xl p-5 shadow-sm space-y-4">
        <h3 className="text-sm font-semibold uppercase tracking-wider text-white flex items-center gap-2">
          <svg className="w-4 h-4 text-purple-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
          </svg>
          Decision History ({decisions.length})
        </h3>

        {decisions.length === 0 ? (
          <p className="text-xs text-gray-400 italic">
            No decisions recorded for this finding yet.
          </p>
        ) : (
          <div className="space-y-3">
            {decisions.map((dec) => {
              const isPending = dec.status === "pending";

              return (
                <div
                  key={dec.id}
                  className={`p-3.5 rounded-lg border text-xs space-y-2 ${
                    isPending
                      ? "bg-amber-500/10 border-amber-500/30"
                      : dec.status === "approved"
                      ? "bg-emerald-500/5 border-emerald-500/20"
                      : "bg-red-500/5 border-red-500/20"
                  }`}
                >
                  <div className="flex items-center justify-between flex-wrap gap-2">
                    <div className="flex items-center gap-2">
                      <span className="font-semibold text-white">
                        {formatDecisionType(dec.type)}
                      </span>

                      {/* Status Chip */}
                      <span
                        className={`px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider border ${
                          dec.status === "approved"
                            ? "bg-emerald-500/20 text-emerald-300 border-emerald-500/35"
                            : dec.status === "rejected"
                            ? "bg-red-500/20 text-red-300 border-red-500/35"
                            : "bg-amber-500/20 text-amber-300 border-amber-500/35"
                        }`}
                      >
                        {isPending ? "Pending Admin Approval" : dec.status}
                      </span>
                    </div>

                    <div className="text-[11px] text-gray-400">
                      <span>By <strong>{dec.by}</strong></span>
                      {dec.created_at && (
                        <span className="ml-2 font-mono">
                          {new Date(dec.created_at).toLocaleDateString()}
                        </span>
                      )}
                    </div>
                  </div>

                  <p className="text-gray-300 leading-relaxed font-sans">{dec.reason}</p>

                  <div className="flex items-center justify-between flex-wrap gap-2 pt-1 border-t border-border/50 text-[11px] text-gray-400">
                    <div className="flex items-center gap-3">
                      {dec.expires_at && (
                        <span>
                          Expires:{" "}
                          <strong className="text-gray-200">
                            {new Date(dec.expires_at).toLocaleDateString()}
                          </strong>
                        </span>
                      )}
                      {dec.approved_by && (
                        <span>
                          Approved by:{" "}
                          <strong className="text-gray-200">{dec.approved_by}</strong>
                        </span>
                      )}
                    </div>

                    {/* Admin Approve / Reject actions */}
                    {isPending && canApprove && (
                      <div className="flex items-center gap-2">
                        <button
                          type="button"
                          disabled={processingDecisionId === dec.id}
                          onClick={() => handleApprove(dec.id)}
                          className="px-2.5 py-1 bg-emerald-600 hover:bg-emerald-500 text-white rounded font-medium transition-colors"
                        >
                          Approve
                        </button>
                        <button
                          type="button"
                          disabled={processingDecisionId === dec.id}
                          onClick={() => handleReject(dec.id)}
                          className="px-2.5 py-1 bg-red-600 hover:bg-red-500 text-white rounded font-medium transition-colors"
                        >
                          Reject
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* ════════════════════════════════════════════════════════════════
          INVESTIGATION MEMORY SECTION
          ════════════════════════════════════════════════════════════════ */}
      <div className="bg-bg-surface border border-border rounded-xl p-5 shadow-sm space-y-4">
        <h3 className="text-sm font-semibold uppercase tracking-wider text-white flex items-center gap-2">
          <svg className="w-4 h-4 text-cyan-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z" />
            <path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z" />
          </svg>
          Past Investigations & Memory ({investigations.length})
        </h3>

        {investigations.length === 0 ? (
          <p className="text-xs text-gray-400 italic">
            No past investigations logged for this finding.
          </p>
        ) : (
          <div className="space-y-3">
            {investigations.map((inv) => (
              <div
                key={inv.id}
                className="p-3.5 rounded-lg border border-border bg-bg-card/50 text-xs space-y-2"
              >
                <div className="flex items-center justify-between flex-wrap gap-2">
                  <div className="flex items-center gap-2">
                    <span className="font-semibold text-white">
                      Investigated by <strong>{inv.by}</strong>
                    </span>
                    <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-cyan-500/15 text-cyan-300 border border-cyan-500/30">
                      Verdict: {inv.verdict}
                    </span>
                    {inv.score !== undefined && (
                      <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-slate-700 text-gray-200">
                        Score: {inv.score}
                      </span>
                    )}
                  </div>

                  <span className="text-[11px] text-gray-400 font-mono">
                    {new Date(inv.created_at).toLocaleString()}
                  </span>
                </div>

                {inv.summary && (
                  <p className="text-gray-300 leading-relaxed font-sans">{inv.summary}</p>
                )}

                {inv.session_id && (
                  <div className="text-[10px] text-gray-500 font-mono">
                    Session ID: {inv.session_id}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};
