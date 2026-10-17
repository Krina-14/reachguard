import { useEffect } from "react";

export function useDocumentTitle(title: string) {
  useEffect(() => {
    const previous = document.title;
    document.title = title
      ? `${title} | ReachGuard`
      : "ReachGuard — Reachability-driven Vulnerability Prioritization";
    return () => {
      document.title = previous;
    };
  }, [title]);
}
