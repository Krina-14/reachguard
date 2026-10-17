import React, { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/useAuth";
import { ApiError } from "../api/types";
import { useDocumentTitle } from "../lib/useDocumentTitle";

interface QuickAccount {
  role: "admin" | "analyst" | "viewer";
  label: string;
  email: string;
  secret: string;
  description: string;
  badgeClass: string;
}

const QUICK_ACCOUNTS: QuickAccount[] = [
  {
    role: "admin",
    label: "Admin",
    email: "admin@reachguard.io",
    secret: "AdminPass!123",
    description: "Full privileges & user management",
    badgeClass: "bg-purple-500/20 text-purple-300 border-purple-500/40",
  },
  {
    role: "analyst",
    label: "Analyst",
    email: "analyst@reachguard.io",
    secret: "AnalystPass!123",
    description: "Analyze repos, investigate & accept risk",
    badgeClass: "bg-blue-500/20 text-blue-300 border-blue-500/40",
  },
  {
    role: "viewer",
    label: "Viewer",
    email: "viewer@reachguard.io",
    secret: "ViewerPass!123",
    description: "Read-only findings & call-graphs",
    badgeClass: "bg-slate-500/20 text-slate-300 border-slate-500/40",
  },
];

export const LoginPage: React.FC = () => {
  useDocumentTitle("Sign In");
  const { login, isAuthenticated } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const emailInputRef = useRef<HTMLInputElement>(null);

  // Focus on the first field (email) on mount
  useEffect(() => {
    emailInputRef.current?.focus();
  }, []);

  // Redirect if already authenticated
  const from = (location.state as { from?: { pathname: string } })?.from?.pathname || "/";
  useEffect(() => {
    if (isAuthenticated) {
      navigate(from, { replace: true });
    }
  }, [isAuthenticated, navigate, from]);

  const performLogin = async (loginEmail: string, loginPass: string) => {
    setErrorMessage(null);
    setIsSubmitting(true);

    try {
      await login(loginEmail.trim(), loginPass);
      navigate(from, { replace: true });
    } catch (err: unknown) {
      if (err instanceof ApiError) {
        if (err.statusCode === 429 || err.code === 429 || err.code === "429") {
          setErrorMessage("Too many attempts, wait a minute");
        } else {
          setErrorMessage(err.message || "Invalid email or password");
        }
      } else if (err instanceof Error) {
        setErrorMessage(err.message);
      } else {
        setErrorMessage("An unexpected authentication error occurred");
      }
      setIsSubmitting(false);
    }
  };

  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    await performLogin(email, password);
  };

  const handleQuickLogin = async (acc: QuickAccount) => {
    setEmail(acc.email);
    setPassword(acc.secret);
    await performLogin(acc.email, acc.secret);
  };

  return (
    <div className="min-h-screen bg-bg flex flex-col justify-center items-center px-4 py-12">
      <div className="w-full max-w-md">
        {/* Brand Header */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-12 h-12 rounded-xl bg-accent/15 border border-accent/30 text-accent mb-4">
            <svg
              className="w-7 h-7"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
            </svg>
          </div>
          <h1 className="text-3xl font-bold tracking-tight text-white">
            ReachGuard
          </h1>
          <p className="text-sm text-gray-400 mt-1">
            Vulnerability Reachability & Call-Graph Intelligence
          </p>
        </div>

        {/* Quick Role Sign-in Card */}
        <div className="bg-bg-surface border border-accent/30 rounded-xl p-5 mb-5 shadow-xl">
          <div className="flex items-center justify-between mb-3">
            <span className="text-xs font-semibold uppercase tracking-wider text-accent flex items-center gap-1.5">
              <svg
                className="w-3.5 h-3.5 text-accent"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
              >
                <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
              </svg>
              Quick Role Sign In
            </span>
            <span className="text-[11px] text-gray-400">1-click access</span>
          </div>

          <div className="grid grid-cols-3 gap-2.5">
            {QUICK_ACCOUNTS.map((acc) => (
              <button
                key={acc.role}
                type="button"
                disabled={isSubmitting}
                onClick={() => handleQuickLogin(acc)}
                className="flex flex-col items-center text-center p-2.5 rounded-lg bg-bg-card hover:bg-bg-subtle border border-border hover:border-accent/50 transition-all cursor-pointer group disabled:opacity-50"
                title={`${acc.email} — ${acc.description}`}
              >
                <span
                  className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider border mb-1.5 ${acc.badgeClass}`}
                >
                  {acc.label}
                </span>
                <span className="text-[10px] text-gray-400 group-hover:text-white transition-colors truncate w-full">
                  {acc.email.split("@")[0]}
                </span>
              </button>
            ))}
          </div>
        </div>

        {/* Login Card */}
        <div className="bg-bg-surface border border-border rounded-xl p-8 shadow-2xl backdrop-blur-md">
          <h2 className="text-xl font-semibold text-white mb-6">Sign In with Credentials</h2>

          {errorMessage && (
            <div
              role="alert"
              className="mb-6 p-3.5 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 text-sm flex items-start gap-2.5 animate-in fade-in duration-200"
            >
              <svg
                className="w-5 h-5 flex-shrink-0 mt-0.5"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
              >
                <circle cx="12" cy="12" r="10" />
                <line x1="12" y1="8" x2="12" y2="12" />
                <line x1="12" y1="16" x2="12.01" y2="16" />
              </svg>
              <span className="leading-relaxed">{errorMessage}</span>
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-5" noValidate={false}>
            <div>
              <label
                htmlFor="login-email"
                className="block text-xs font-medium text-gray-300 uppercase tracking-wider mb-2"
              >
                Email Address
              </label>
              <input
                id="login-email"
                name="email"
                type="email"
                ref={emailInputRef}
                autoComplete="email"
                required
                disabled={isSubmitting}
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="analyst@reachguard.io"
                className="w-full px-3.5 py-2.5 bg-bg-card border border-border rounded-lg text-white text-sm placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-accent focus:border-transparent transition-all disabled:opacity-50"
              />
            </div>

            <div>
              <label
                htmlFor="login-password"
                className="block text-xs font-medium text-gray-300 uppercase tracking-wider mb-2"
              >
                Password
              </label>
              <input
                id="login-password"
                name="password"
                type="password"
                autoComplete="current-password"
                required
                disabled={isSubmitting}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••••••"
                className="w-full px-3.5 py-2.5 bg-bg-card border border-border rounded-lg text-white text-sm placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-accent focus:border-transparent transition-all disabled:opacity-50"
              />
            </div>

            <button
              type="submit"
              disabled={isSubmitting}
              className="w-full py-2.5 px-4 bg-accent hover:bg-accent-hover active:bg-accent/90 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-semibold rounded-lg shadow-lg shadow-accent/20 transition-all flex items-center justify-center gap-2 mt-2"
            >
              {isSubmitting ? (
                <>
                  <svg
                    className="animate-spin h-4 w-4 text-white"
                    viewBox="0 0 24 24"
                    fill="none"
                  >
                    <circle
                      className="opacity-25"
                      cx="12"
                      cy="12"
                      r="10"
                      stroke="currentColor"
                      strokeWidth="4"
                    />
                    <path
                      className="opacity-75"
                      fill="currentColor"
                      d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                    />
                  </svg>
                  <span>Authenticating...</span>
                </>
              ) : (
                <span>Sign In</span>
              )}
            </button>
          </form>
        </div>

        <p className="text-center text-xs text-gray-500 mt-6">
          ReachGuard Security Intelligence Platform • Contract Version 0.1.0
        </p>
      </div>
    </div>
  );
};
