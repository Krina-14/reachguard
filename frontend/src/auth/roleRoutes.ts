import type { UserRole } from "../api/types";

export function getRoleHomeRoute(role?: UserRole | string | null): string {
  switch (role) {
    case "admin":
      return "/control";
    case "analyst":
      return "/triage";
    case "viewer":
      return "/overview";
    default:
      return "/overview";
  }
}

export const ROLE_DESCRIPTIONS: Record<UserRole, string> = {
  viewer: "Read-only access: view repositories, findings, call-graphs, and ask questions.",
  analyst: "Analyze repositories, run what-if simulations, record decisions, and save investigations.",
  admin: "Full administrative access: approve decisions, manage users, and configure repositories.",
};
