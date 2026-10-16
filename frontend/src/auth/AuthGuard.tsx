import React from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "./useAuth";
import type { UserRole } from "../api/types";

interface AuthGuardProps {
  children: React.ReactNode;
  requiredRole?: UserRole;
}

export const AuthGuard: React.FC<AuthGuardProps> = ({
  children,
  requiredRole,
}) => {
  const { user, isAuthenticated, isLoading } = useAuth();
  const location = useLocation();

  if (isLoading) {
    return (
      <div className="min-h-screen bg-bg flex items-center justify-center">
        <div className="text-gray-400 text-sm font-mono animate-pulse">
          Authenticating session...
        </div>
      </div>
    );
  }

  if (!isAuthenticated || !user) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  if (requiredRole && user.role !== requiredRole && user.role !== "admin") {
    return <Navigate to="/" replace />;
  }

  return <>{children}</>;
};
