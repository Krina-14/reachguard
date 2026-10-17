import React, { useState, useRef, useEffect, useMemo } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "../api/client";
import { useCan } from "../auth/useCan";
import { ApiError } from "../api/types";
import type {
  ChatRequest,
  ChatResponse,
  FindingRow,
  AgentMode,
} from "../api/types";

interface ChatPanelProps {
  repoId: string;
  currentFindingId?: string;
  findings?: FindingRow[];
  onHighlightPath?: (findingId: string) => void;
}

interface MessageItem {
  id: string;
  role: "user" | "assistant" | "error";
  content: string;
  timestamp: Date;
  response?: ChatResponse;
  errorMessage?: string;
}

export const ChatPanel: React.FC<ChatPanelProps> = ({
  repoId,
  currentFindingId,
  findings: propFindings,
  onHighlightPath,
}) => {
  const navigate = useNavigate();
  const { canSave } = useCan(); // Only analyst and admin can save investigations

  const [isOpen, setIsOpen] = useState(false);
  const [messages, setMessages] = useState<MessageItem[]>([]);
  const [inputValue, setInputValue] = useState("");
  const [sessionId, setSessionId] = useState<string>(() => crypto.randomUUID());
  const [saveInvestigation, setSaveInvestigation] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [expandedEvidenceIds, setExpandedEvidenceIds] = useState<Set<string>>(
    new Set()
  );

  const abortControllerRef = useRef<AbortController | null>(null);
  const timerRef = useRef<number | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // If findings are not provided as props, fetch them so we can build starter questions
  const { data: fetchedFindings } = useQuery<FindingRow[]>({
    queryKey: ["findings", repoId],
    queryFn: () => apiFetch<FindingRow[]>(`/api/repos/${repoId}/findings`),
    enabled: Boolean(repoId && !propFindings),
    staleTime: 30000,
  });

  const allFindings = useMemo(
    () => propFindings || fetchedFindings || [],
    [propFindings, fetchedFindings]
  );

  // Scroll to bottom when messages update or during loading
  useEffect(() => {
    if (isOpen) {
      messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages, isLoading, isOpen]);

  // Manage elapsed seconds timer while waiting for LLM
  useEffect(() => {
    if (isLoading) {
      setElapsedSeconds(0);
      timerRef.current = window.setInterval(() => {
        setElapsedSeconds((prev) => prev + 1);
      }, 1000);
    } else {
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
    }
    return () => {
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
    };
  }, [isLoading]);

  // Cleanup abort controller on unmount
  useEffect(() => {
    return () => {
      abortControllerRef.current?.abort();
    };
  }, []);

  // Suggested starter questions built dynamically from findings list
  const suggestedQuestions = useMemo(() => {
    if (!allFindings || allFindings.length === 0) return [];

    const top = allFindings[0];
    const questions: string[] = [];

    if (currentFindingId) {
      questions.push(
        `Can ${currentFindingId} be reached from any public entrypoint?`
      );
    }

    if (top?.package) {
      questions.push(`Why is ${top.package} ranked first?`);
      if (top.vuln_id) {
        questions.push(`How can we mitigate ${top.vuln_id} on ${top.package}?`);
      }
    }

    questions.push("What are the primary choke points across all packages?");

    if (allFindings.length > 1 && allFindings[1]?.package) {
      questions.push(
        `Compare reachability risk of ${top.package} vs ${allFindings[1].package}.`
      );
    }

    return questions.slice(0, 4);
  }, [allFindings, currentFindingId]);

  // Handle "New session"
  const handleNewSession = () => {
    abortControllerRef.current?.abort();
    setIsLoading(false);
    setSessionId(crypto.randomUUID());
    setMessages([]);
    setInputValue("");
    setExpandedEvidenceIds(new Set());
  };

  // Cancel in-flight request
  const handleCancel = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    setIsLoading(false);
    setMessages((prev) => [
      ...prev,
      {
        id: crypto.randomUUID(),
        role: "error",
        content: "Investigation request canceled by user.",
        timestamp: new Date(),
        errorMessage: "Request aborted",
      },
    ]);
  };

  // Send message
  const handleSendMessage = async (textToSend?: string) => {
    const rawText = textToSend !== undefined ? textToSend : inputValue;
    const trimmed = rawText.trim();
    if (!trimmed || isLoading) return;

    const userMessageId = crypto.randomUUID();
    const newUserMessage: MessageItem = {
      id: userMessageId,
      role: "user",
      content: trimmed,
      timestamp: new Date(),
    };

    setMessages((prev) => [...prev, newUserMessage]);
    setInputValue("");
    setIsLoading(true);

    const controller = new AbortController();
    abortControllerRef.current = controller;

    const payload: ChatRequest = {
      message: trimmed,
      session_id: sessionId || undefined,
      save: canSave ? saveInvestigation : false,
    };

    try {
      const response = await apiFetch<ChatResponse>(
        `/api/repos/${repoId}/agent/chat`,
        {
          method: "POST",
          body: JSON.stringify(payload),
          signal: controller.signal,
        }
      );

      // Keep updated session ID
      if (response.session_id) {
        setSessionId(response.session_id);
      }

      const assistantMessage: MessageItem = {
        id: crypto.randomUUID(),
        role: "assistant",
        content: response.answer,
        timestamp: new Date(),
        response,
      };

      setMessages((prev) => [...prev, assistantMessage]);
    } catch (err: unknown) {
      if (controller.signal.aborted) {
        // User deliberately aborted; already handled in handleCancel
        return;
      }

      let friendlyMessage = "Failed to communicate with AI Triage Agent.";

      if (err instanceof ApiError) {
        if (err.statusCode === 403) {
          friendlyMessage =
            "Permission Denied (403): Only analysts and administrators can save investigations. Please disable the 'Save investigation' toggle and try again.";
        } else if (err.statusCode === 429) {
          friendlyMessage =
            "Rate Limit Exceeded (429): You have sent too many requests. Please wait a minute before asking another question.";
        } else if (err.statusCode === 404) {
          friendlyMessage =
            "Repository or finding was not found (404). Please verify that the repository exists.";
        } else if (err.statusCode === 409) {
          friendlyMessage =
            "Repository analysis is still processing (409). Please wait until the ingestion pipeline completes.";
        } else {
          friendlyMessage = `API Error (${err.statusCode}): ${err.message}`;
        }
      } else if (err instanceof Error) {
        friendlyMessage = `Network / Client Error: ${err.message}`;
      }

      setMessages((prev) => [
        ...prev,
        {
          id: crypto.randomUUID(),
          role: "error",
          content: friendlyMessage,
          timestamp: new Date(),
          errorMessage: friendlyMessage,
        },
      ]);
    } finally {
      setIsLoading(false);
      abortControllerRef.current = null;
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
  };

  const toggleEvidenceExpanded = (messageId: string) => {
    setExpandedEvidenceIds((prev) => {
      const next = new Set(prev);
      if (next.has(messageId)) {
        next.delete(messageId);
      } else {
        next.add(messageId);
      }
      return next;
    });
  };

  const handleShowPath = (findingId: string) => {
    if (onHighlightPath) {
      onHighlightPath(findingId);
    }
    // Navigate to finding page if not already there
    navigate(`/repos/${repoId}/findings/${findingId}`);
  };

  // Helper to render mode chip
  const renderModeChip = (mode: AgentMode | string) => {
    switch (mode) {
      case "llm_tools":
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-semibold bg-sky-500/15 text-sky-300 border border-sky-500/30">
            <span className="w-1.5 h-1.5 rounded-full bg-sky-400" />
            LLM + tools
          </span>
        );
      case "llm_explain":
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-semibold bg-purple-500/15 text-purple-300 border border-purple-500/30">
            <span className="w-1.5 h-1.5 rounded-full bg-purple-400" />
            LLM explanation
          </span>
        );
      case "deterministic":
      default:
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-semibold bg-slate-500/15 text-slate-300 border border-slate-500/30">
            <span className="w-1.5 h-1.5 rounded-full bg-slate-400" />
            Deterministic
          </span>
        );
    }
  };

  /**
   * Parse answer text and turn finding IDs into links ONLY IF the ID exists in evidence.findings.
   */
  const renderLinkedAnswerText = (
    text: string,
    evidenceFindings?: FindingRow[]
  ) => {
    if (!evidenceFindings || evidenceFindings.length === 0) {
      return <span>{text}</span>;
    }

    // Build lookup map of valid finding IDs and vuln IDs in evidence.findings
    const validFindingMap = new Map<string, string>(); // token lowercase -> target finding_id
    for (const f of evidenceFindings) {
      if (f.id) {
        validFindingMap.set(f.id.toLowerCase(), f.id);
      }
      if (f.vuln_id) {
        validFindingMap.set(f.vuln_id.toLowerCase(), f.id || f.vuln_id);
      }
    }

    // Tokenize text while preserving words, IDs, punctuation, and whitespace
    const regex =
      /\b(?:[a-f0-9]{12}|find-[a-zA-Z0-9_-]+|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}|GHSA-[a-zA-Z0-9-]+|CVE-\d{4}-\d+)\b/gi;

    const parts: React.ReactNode[] = [];
    let lastIndex = 0;
    let match: RegExpExecArray | null;

    while ((match = regex.exec(text)) !== null) {
      const matchIndex = match.index;
      const matchedWord = match[0];

      // Add preceding plain text
      if (matchIndex > lastIndex) {
        parts.push(text.substring(lastIndex, matchIndex));
      }

      const targetFindingId = validFindingMap.get(matchedWord.toLowerCase());

      if (targetFindingId) {
        // Only link if present in evidence.findings!
        parts.push(
          <Link
            key={`${matchIndex}-${matchedWord}`}
            to={`/repos/${repoId}/findings/${targetFindingId}`}
            className="text-accent hover:underline font-mono font-semibold transition-colors bg-accent/10 px-1 py-0.5 rounded border border-accent/25 hover:bg-accent/20"
            title={`View finding ${targetFindingId}`}
          >
            {matchedWord}
          </Link>
        );
      } else {
        // Not in evidence.findings: render as plain text
        parts.push(matchedWord);
      }

      lastIndex = matchIndex + matchedWord.length;
    }

    if (lastIndex < text.length) {
      parts.push(text.substring(lastIndex));
    }

    return <>{parts}</>;
  };

  return (
    <>
      {/* ── Collapsed Floating Trigger Button ── */}
      {!isOpen && (
        <button
          type="button"
          onClick={() => setIsOpen(true)}
          className="fixed bottom-6 right-6 z-40 px-4 py-2.5 rounded-full bg-accent hover:bg-accent-hover text-white font-medium text-xs shadow-2xl flex items-center gap-2 border border-accent/40 backdrop-blur-md transition-all hover:scale-105 active:scale-95 group"
          title="Open AI Triage Chat"
        >
          <span className="relative flex h-2 w-2">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-white opacity-75" />
            <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-400" />
          </span>
          <svg className="w-4 h-4 text-white group-hover:rotate-12 transition-transform" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
          </svg>
          <span className="font-semibold tracking-wide">Triage AI Chat</span>
        </button>
      )}

      {/* ── Expanded Right-Side Collapsible Drawer Panel ── */}
      {isOpen && (
        <div className="fixed top-0 right-0 bottom-0 w-[440px] max-w-[95vw] bg-bg-surface border-l border-border z-50 flex flex-col shadow-2xl animate-in slide-in-from-right duration-200">
          {/* Header */}
          <div className="p-4 border-b border-border bg-bg-card/70 flex items-center justify-between shrink-0">
            <div className="flex items-center gap-2 min-w-0">
              <span className="p-1.5 rounded-lg bg-accent/20 text-accent border border-accent/30">
                <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83" />
                </svg>
              </span>
              <div className="min-w-0">
                <h3 className="text-sm font-bold text-white flex items-center gap-1.5 truncate">
                  ReachGuard AI Triage
                </h3>
                <span className="text-[10px] text-gray-400 block truncate font-mono">
                  Session: {sessionId.substring(0, 8)}...
                </span>
              </div>
            </div>

            <div className="flex items-center gap-1.5 shrink-0">
              {/* New session button */}
              <button
                type="button"
                onClick={handleNewSession}
                className="px-2 py-1 text-[11px] rounded bg-bg-surface hover:bg-slate-700 text-gray-300 border border-border transition-colors flex items-center gap-1"
                title="Start a new chat session"
              >
                <svg className="w-3 h-3 text-gray-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M12 5v14M5 12h14" />
                </svg>
                New session
              </button>

              {/* Close/Collapse button */}
              <button
                type="button"
                onClick={() => setIsOpen(false)}
                className="p-1.5 rounded hover:bg-slate-700 text-gray-400 hover:text-white transition-colors"
                title="Collapse chat panel"
              >
                <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <line x1="18" y1="6" x2="6" y2="18" />
                  <line x1="6" y1="6" x2="18" y2="18" />
                </svg>
              </button>
            </div>
          </div>

          {/* Messages & Conversation Scroll Area */}
          <div className="flex-1 overflow-y-auto p-4 space-y-4">
            {/* Empty State / Suggested Questions */}
            {messages.length === 0 && (
              <div className="space-y-4 py-4">
                <div className="p-4 rounded-xl bg-bg-card/60 border border-border/80 text-center space-y-2">
                  <div className="w-10 h-10 mx-auto rounded-full bg-accent/15 flex items-center justify-center text-accent">
                    <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <circle cx="12" cy="12" r="10" />
                      <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3" />
                      <line x1="12" y1="17" x2="12.01" y2="17" />
                    </svg>
                  </div>
                  <h4 className="text-xs font-bold text-white uppercase tracking-wider">
                    Ask Triage Questions
                  </h4>
                  <p className="text-xs text-gray-400 leading-relaxed">
                    Ask about vulnerability reachability, public call paths, choke
                    point mitigations, or prior decisions.
                  </p>
                </div>

                {/* Suggested starter questions as buttons (ONLY if findings exist) */}
                {suggestedQuestions.length > 0 && (
                  <div className="space-y-2">
                    <span className="text-[11px] font-semibold uppercase tracking-wider text-gray-400 block px-1">
                      Suggested Questions
                    </span>
                    <div className="flex flex-col gap-1.5">
                      {suggestedQuestions.map((q, idx) => (
                        <button
                          key={idx}
                          type="button"
                          onClick={() => handleSendMessage(q)}
                          className="w-full text-left p-2.5 rounded-lg bg-bg-card hover:bg-slate-800 text-xs text-gray-300 hover:text-white border border-border hover:border-accent/40 transition-all flex items-center justify-between group"
                        >
                          <span className="truncate pr-2">{q}</span>
                          <span className="text-accent opacity-0 group-hover:opacity-100 transition-opacity">
                            →
                          </span>
                        </button>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* Render Messages */}
            {messages.map((msg) => {
              const isUser = msg.role === "user";
              const isError = msg.role === "error";

              if (isError) {
                return (
                  <div
                    key={msg.id}
                    className="p-3 rounded-lg bg-red-500/10 border border-red-500/30 text-xs text-red-300 space-y-1 animate-fade-in"
                  >
                    <div className="flex items-center gap-1.5 font-semibold text-red-200">
                      <svg className="w-3.5 h-3.5 text-red-400 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <circle cx="12" cy="12" r="10" />
                        <line x1="12" y1="8" x2="12" y2="12" />
                        <line x1="12" y1="16" x2="12.01" y2="16" />
                      </svg>
                      Error
                    </div>
                    <p className="leading-relaxed text-red-300">
                      {msg.errorMessage || msg.content}
                    </p>
                  </div>
                );
              }

              if (isUser) {
                return (
                  <div key={msg.id} className="flex justify-end">
                    <div className="max-w-[85%] rounded-2xl rounded-br-sm px-4 py-2.5 bg-accent text-white text-xs shadow-md leading-relaxed break-words whitespace-pre-wrap">
                      {msg.content}
                    </div>
                  </div>
                );
              }

              // Assistant message
              const resp = msg.response;
              const isEvidenceExpanded = expandedEvidenceIds.has(msg.id);
              const toolCalls = resp?.tool_calls || [];
              const traces = (resp?.evidence?.traces || []) as Array<{
                finding_id: string;
                verdict: string;
                paths?: unknown[];
              }>;
              const hasEvidence =
                toolCalls.length > 0 ||
                traces.length > 0 ||
                Boolean(resp?.evidence?.findings?.length);

              return (
                <div key={msg.id} className="flex flex-col gap-2.5 max-w-[95%]">
                  <div className="rounded-2xl rounded-tl-sm p-4 bg-bg-card border border-border text-xs text-gray-200 space-y-3 shadow-sm leading-relaxed break-words">
                    {/* Message Body with Linked Finding IDs */}
                    <div className="whitespace-pre-wrap leading-relaxed">
                      {renderLinkedAnswerText(
                        msg.content,
                        resp?.evidence?.findings
                      )}
                    </div>

                    {/* Metadata Footer: Mode chip & Grounded indicator */}
                    {resp && (
                      <div className="pt-2 border-t border-border/70 flex flex-wrap items-center justify-between gap-2 text-[11px]">
                        {/* Mode Chip */}
                        <div>{renderModeChip(resp.mode)}</div>

                        {/* Grounded Check Mark */}
                        <div className="flex items-center gap-1.5">
                          {resp.grounded ? (
                            <span
                              className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-semibold bg-emerald-500/15 text-emerald-300 border border-emerald-500/30"
                              title="Answer is strictly verified against graph model evidence"
                            >
                              <svg className="w-3 h-3 text-emerald-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                                <polyline points="20 6 9 17 4 12" />
                              </svg>
                              Grounded
                            </span>
                          ) : (
                            <div className="flex flex-col items-end">
                              <span
                                className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-semibold bg-amber-500/15 text-amber-300 border border-amber-500/30"
                                title="Grounding checks flagged potential unverified claims"
                              >
                                <svg className="w-3 h-3 text-amber-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                                  <polygon points="7.86 2 16.14 2 22 7.86 22 16.14 16.14 22 7.86 22 2 16.14 2 7.86 7.86 2" />
                                  <line x1="12" y1="8" x2="12" y2="12" />
                                  <line x1="12" y1="16" x2="12.01" y2="16" />
                                </svg>
                                Ungrounded
                              </span>
                            </div>
                          )}
                        </div>
                      </div>
                    )}

                    {/* Warnings List if Grounded is False */}
                    {resp && !resp.grounded && resp.warnings && resp.warnings.length > 0 && (
                      <div className="p-2.5 rounded bg-amber-500/10 border border-amber-500/30 text-[11px] text-amber-300 space-y-1">
                        <span className="font-semibold block text-amber-200">
                          Grounding Warnings:
                        </span>
                        <ul className="list-disc list-inside space-y-0.5">
                          {resp.warnings.map((w, wIdx) => (
                            <li key={wIdx}>{w}</li>
                          ))}
                        </ul>
                      </div>
                    )}

                    {/* Expandable Evidence Section */}
                    {hasEvidence && (
                      <div className="pt-1">
                        <button
                          type="button"
                          onClick={() => toggleEvidenceExpanded(msg.id)}
                          className="w-full flex items-center justify-between py-1.5 px-2 rounded bg-bg-surface hover:bg-slate-700/60 border border-border/60 text-[11px] font-medium text-gray-300 transition-colors"
                        >
                          <span className="flex items-center gap-1.5">
                            <svg className="w-3.5 h-3.5 text-accent" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                              <polygon points="12 2 2 7 12 12 22 7 12 2" />
                              <polyline points="2 17 12 22 22 17" />
                              <polyline points="2 12 12 17 22 12" />
                            </svg>
                            Evidence ({toolCalls.length} tools, {traces.length}{" "}
                            traces)
                          </span>
                          <span className="text-gray-400 text-xs">
                            {isEvidenceExpanded ? "▲ Hide" : "▼ Show"}
                          </span>
                        </button>

                        {isEvidenceExpanded && (
                          <div className="mt-2 space-y-3 p-2.5 rounded-lg bg-bg-surface/90 border border-border text-[11px] font-sans">
                            {/* Tool Calls List */}
                            {toolCalls.length > 0 && (
                              <div className="space-y-1.5">
                                <span className="font-semibold text-gray-400 uppercase tracking-wider text-[10px] block">
                                  Tool Invocations
                                </span>
                                <div className="space-y-1.5">
                                  {toolCalls.map((tc, tcIdx) => (
                                    <div
                                      key={tcIdx}
                                      className="p-2 rounded bg-bg-card border border-border/80 space-y-1"
                                    >
                                      <div className="flex items-center justify-between">
                                        <span className="font-mono font-semibold text-accent text-xs">
                                          {tc.name}
                                        </span>
                                        <span
                                          className={`px-1.5 py-0.5 rounded text-[9px] font-mono font-bold ${
                                            tc.ok
                                              ? "bg-emerald-500/20 text-emerald-300"
                                              : "bg-red-500/20 text-red-300"
                                          }`}
                                        >
                                          {tc.ok ? "OK" : "ERROR"}
                                        </span>
                                      </div>
                                      {tc.args && Object.keys(tc.args).length > 0 && (
                                        <div className="text-[10px] font-mono text-gray-400 break-all bg-bg-surface p-1 rounded border border-border/40">
                                          {JSON.stringify(tc.args)}
                                        </div>
                                      )}
                                      {tc.summary && (
                                        <p className="text-[11px] text-gray-300 italic">
                                          {tc.summary}
                                        </p>
                                      )}
                                    </div>
                                  ))}
                                </div>
                              </div>
                            )}

                            {/* Evidence Traces with "Show path" Button */}
                            {traces.length > 0 && (
                              <div className="space-y-1.5 pt-1">
                                <span className="font-semibold text-gray-400 uppercase tracking-wider text-[10px] block">
                                  Evidence Traces
                                </span>
                                <div className="space-y-1.5">
                                  {traces.map((trace, tIdx) => (
                                    <div
                                      key={tIdx}
                                      className="flex items-center justify-between p-2 rounded bg-bg-card border border-border/80"
                                    >
                                      <div className="min-w-0 pr-2">
                                        <span className="font-mono text-xs text-white block truncate">
                                          {trace.finding_id}
                                        </span>
                                        <span className="text-[10px] text-gray-400">
                                          Verdict:{" "}
                                          <strong className="text-gray-200">
                                            {trace.verdict}
                                          </strong>{" "}
                                          ({trace.paths?.length || 0} paths)
                                        </span>
                                      </div>
                                      <button
                                        type="button"
                                        onClick={() =>
                                          handleShowPath(trace.finding_id)
                                        }
                                        className="px-2.5 py-1 text-[11px] font-medium rounded bg-accent/20 hover:bg-accent/30 text-accent border border-accent/40 transition-colors flex items-center gap-1 shrink-0"
                                        title="Highlight path on call graph or view finding"
                                      >
                                        <svg className="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                                          <polyline points="9 18 15 12 9 6" />
                                        </svg>
                                        Show path
                                      </button>
                                    </div>
                                  ))}
                                </div>
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              );
            })}

            {/* Waiting / Typing Indicator with Elapsed Seconds and Cancel */}
            {isLoading && (
              <div className="flex flex-col gap-2 max-w-[85%] animate-fade-in">
                <div className="p-3.5 rounded-2xl rounded-tl-sm bg-bg-card border border-border text-xs text-gray-300 space-y-2 shadow-sm">
                  <div className="flex items-center gap-3">
                    <div className="flex items-center gap-1">
                      <span className="w-2 h-2 rounded-full bg-accent animate-bounce [animation-delay:-0.3s]" />
                      <span className="w-2 h-2 rounded-full bg-accent animate-bounce [animation-delay:-0.15s]" />
                      <span className="w-2 h-2 rounded-full bg-accent animate-bounce" />
                    </div>
                    <span className="font-medium text-gray-300">
                      Reasoning with graph & LLM ({elapsedSeconds}s)
                    </span>
                  </div>

                  <div className="flex items-center justify-between pt-1 border-t border-border/50">
                    <span className="text-[10px] text-gray-400 italic">
                      Local models may take 30+ seconds
                    </span>
                    <button
                      type="button"
                      onClick={handleCancel}
                      className="px-2 py-0.5 rounded text-[11px] font-medium bg-red-500/15 hover:bg-red-500/25 text-red-300 border border-red-500/35 transition-colors"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>

          {/* Footer Input Area */}
          <div className="p-3 border-t border-border bg-bg-card/70 space-y-2 shrink-0">
            {/* Save Investigation Toggle (Analyst/Admin Only) */}
            {canSave && (
              <div className="flex items-center justify-between px-1 text-xs">
                <label className="flex items-center gap-2 cursor-pointer select-none text-gray-300 hover:text-white">
                  <input
                    type="checkbox"
                    checked={saveInvestigation}
                    onChange={(e) => setSaveInvestigation(e.target.checked)}
                    className="w-3.5 h-3.5 rounded border-border bg-bg-surface text-accent focus:ring-accent"
                  />
                  <span className="text-[11px] font-medium">
                    Save investigation to graph memory
                  </span>
                </label>
                <span className="text-[10px] text-gray-400 font-mono">
                  [analyst+]
                </span>
              </div>
            )}

            {/* Input Box & Action Row */}
            <div className="flex items-end gap-2 bg-bg-surface border border-border rounded-xl p-2 focus-within:border-accent transition-colors">
              <textarea
                ref={textareaRef}
                value={inputValue}
                onChange={(e) => setInputValue(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Ask about reachability, attack paths, or mitigations... (Enter sends, Shift+Enter newline)"
                rows={2}
                disabled={isLoading}
                className="flex-1 bg-transparent text-xs text-white placeholder-gray-500 resize-none outline-none leading-relaxed disabled:opacity-50"
              />

              <button
                type="button"
                disabled={isLoading || !inputValue.trim()}
                onClick={() => handleSendMessage()}
                className="px-3 py-2 rounded-lg bg-accent hover:bg-accent-hover disabled:opacity-40 text-white text-xs font-semibold shadow-sm transition-all flex items-center justify-center shrink-0"
                title="Send message (Enter)"
              >
                <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <line x1="22" y1="2" x2="11" y2="13" />
                  <polygon points="22 2 15 22 11 13 2 9 22 2" />
                </svg>
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
};
