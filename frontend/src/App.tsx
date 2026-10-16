import React from "react";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthProvider } from "./auth/AuthContext";
import { AuthGuard } from "./auth/AuthGuard";
import { LoginPage } from "./pages/LoginPage";
import { ReposPage } from "./pages/ReposPage";
import { RepoDetailPage } from "./pages/RepoDetailPage";
import { FindingDetailPage } from "./pages/FindingDetailPage";
import { AdminUsersPage } from "./pages/AdminUsersPage";
import { NotFoundPage } from "./pages/NotFoundPage";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

export const App: React.FC = () => {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <BrowserRouter>
          <Routes>
            {/* Public route */}
            <Route path="/login" element={<LoginPage />} />

            {/* Protected routes */}
            <Route
              path="/"
              element={
                <AuthGuard>
                  <ReposPage />
                </AuthGuard>
              }
            />
            <Route
              path="/repos/:repoId"
              element={
                <AuthGuard>
                  <RepoDetailPage />
                </AuthGuard>
              }
            />
            <Route
              path="/repos/:repoId/findings/:findingId"
              element={
                <AuthGuard>
                  <FindingDetailPage />
                </AuthGuard>
              }
            />
            <Route
              path="/admin/users"
              element={
                <AuthGuard requiredRole="admin">
                  <AdminUsersPage />
                </AuthGuard>
              }
            />

            {/* Catch-all 404 */}
            <Route path="*" element={<NotFoundPage />} />
          </Routes>
        </BrowserRouter>
      </AuthProvider>
    </QueryClientProvider>
  );
};

export default App;
