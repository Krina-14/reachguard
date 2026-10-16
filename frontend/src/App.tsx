import React from "react";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthProvider } from "./auth/AuthContext";
import { RequireAuth, RequireRole } from "./auth/guards";
import { Layout } from "./components/Layout";
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
              <Route path="/" element={<ReposPage />} />
              <Route path="/repos/:repoId" element={<RepoDetailPage />} />
              <Route
                path="/repos/:repoId/findings/:findingId"
                element={<FindingDetailPage />}
              />
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
  );
};

export default App;
