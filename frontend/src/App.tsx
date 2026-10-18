import React from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthProvider } from "./auth/AuthContext";
import { RequireAuth, RequireRole } from "./auth/guards";
import { useAuth } from "./auth/useAuth";
import { getRoleHomeRoute } from "./auth/roleRoutes";
import { Layout } from "./components/Layout";
import { LoginPage } from "./pages/LoginPage";
import { ReposPage } from "./pages/ReposPage";
import { RepoDetailPage } from "./pages/RepoDetailPage";
import { FindingDetailPage } from "./pages/FindingDetailPage";
import { RepoMemoryPage } from "./pages/RepoMemoryPage";
import { MemoryPage } from "./pages/MemoryPage";
import { AdminUsersPage } from "./pages/AdminUsersPage";
import { OverviewPage } from "./pages/OverviewPage";
import { TriagePage } from "./pages/TriagePage";
import { ControlCenterPage } from "./pages/ControlCenterPage";
import { NotFoundPage } from "./pages/NotFoundPage";

import { ErrorBoundary } from "./components/ErrorBoundary";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

/**
 * Redirects "/" to the role-specific landing page:
 * - viewer -> /overview
 * - analyst -> /triage
 * - admin -> /control
 */
const RoleHomeRedirect: React.FC = () => {
  const { user } = useAuth();
  return <Navigate to={getRoleHomeRoute(user?.role)} replace />;
};

export const App: React.FC = () => {
  return (
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <BrowserRouter>
            <Routes>
              {/* Public authentication route */}
              <Route path="/login" element={<LoginPage />} />

              {/* Protected routes wrapped in Layout and RequireAuth */}
              <Route
                element={
                  <RequireAuth>
                    <Layout />
                  </RequireAuth>
                }
              >
                {/* Root redirects by role */}
                <Route path="/" element={<RoleHomeRedirect />} />

                {/* Role-guarded landing pages */}
                <Route
                  path="/overview"
                  element={
                    <RequireRole roles={["viewer"]}>
                      <OverviewPage />
                    </RequireRole>
                  }
                />
                <Route
                  path="/triage"
                  element={
                    <RequireRole roles={["analyst", "admin"]}>
                      <TriagePage />
                    </RequireRole>
                  }
                />
                <Route
                  path="/control"
                  element={
                    <RequireRole roles={["admin"]}>
                      <ControlCenterPage />
                    </RequireRole>
                  }
                />

                {/* Repositories catalog and details */}
                <Route path="/repos" element={<ReposPage />} />
                <Route path="/repos/:repoId" element={<RepoDetailPage />} />
                <Route path="/repos/:repoId/memory" element={<RepoMemoryPage />} />
                <Route path="/memory" element={<MemoryPage />} />
                <Route
                  path="/repos/:repoId/findings/:findingId"
                  element={<FindingDetailPage />}
                />

                {/* Role-guarded admin users page */}
                <Route
                  path="/admin/users"
                  element={
                    <RequireRole roles={["admin"]}>
                      <AdminUsersPage />
                    </RequireRole>
                  }
                />
              </Route>

              {/* Catch-all route */}
              <Route path="*" element={<NotFoundPage />} />
            </Routes>
          </BrowserRouter>
        </AuthProvider>
      </QueryClientProvider>
    </ErrorBoundary>
  );
};

export default App;
