/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        /* Design System: Restrained Dark Neutrals */
        bg: {
          DEFAULT: "#0b0f19",
          surface: "#111827",
          card: "#161f30",
          subtle: "#1e293b",
        },
        border: {
          DEFAULT: "#1e293b",
          subtle: "rgba(255, 255, 255, 0.08)",
          strong: "rgba(255, 255, 255, 0.16)",
        },

        /* Single Primary Accent Color */
        accent: {
          DEFAULT: "#3b82f6", // ReachGuard primary blue
          hover: "#2563eb",
          subtle: "rgba(59, 130, 246, 0.15)",
          border: "rgba(59, 130, 246, 0.35)",
        },

        /*
         * ReachGuard Verdict Colors
         * Each verdict is distinguished by both distinct color AND dedicated icon/label:
         * 1. reachable_in_model -> Red (#ef4444) with "path" icon (route/branch)
         * 2. unknown            -> Amber (#f59e0b) with "?" icon (help/question)
         * 3. no_path_found      -> Slate (#64748b) with "dash" icon (minus/dash)
         */
        verdict: {
          reachable: {
            DEFAULT: "#ef4444",
            bg: "rgba(239, 68, 68, 0.15)",
            border: "rgba(239, 68, 68, 0.35)",
            text: "#f87171",
          },
          unknown: {
            DEFAULT: "#f59e0b",
            bg: "rgba(245, 158, 11, 0.15)",
            border: "rgba(245, 158, 11, 0.35)",
            text: "#fbbf24",
          },
          nopath: {
            DEFAULT: "#64748b",
            bg: "rgba(100, 116, 139, 0.15)",
            border: "rgba(100, 116, 139, 0.35)",
            text: "#94a3b8",
          },
        },
      },
      fontFamily: {
        sans: ["Inter", "-apple-system", "BlinkMacSystemFont", "Segoe UI", "sans-serif"],
        mono: ["JetBrains Mono", "Fira Code", "Consolas", "monospace"],
      },
    },
  },
  plugins: [],
};
