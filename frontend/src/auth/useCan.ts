import { useAuth } from "./useAuth";

// ── Role Permissions Hook (Contract Section 3) ─────────────────────

export interface UserPermissions {
  canAddRepo: boolean;
  canSave: boolean;
  canApprove: boolean;
  canManageUsers: boolean;
}

/**
 * Computes user capabilities strictly from role per Contract Section 3:
 * - viewer:  canAddRepo=false, canSave=false, canApprove=false, canManageUsers=false
 * - analyst: canAddRepo=true,  canSave=true,  canApprove=false, canManageUsers=false
 * - admin:   canAddRepo=true,  canSave=true,  canApprove=true,  canManageUsers=true
 */
export function useCan(): UserPermissions {
  const { user } = useAuth();
  const role = user?.role;

  return {
    canAddRepo: role === "analyst" || role === "admin",
    canSave: role === "analyst" || role === "admin",
    canApprove: role === "admin",
    canManageUsers: role === "admin",
  };
}
