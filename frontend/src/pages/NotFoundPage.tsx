import React from "react";
import { Link } from "react-router-dom";
import { useDocumentTitle } from "../lib/useDocumentTitle";

export const NotFoundPage: React.FC = () => {
  useDocumentTitle("Page Not Found");
  return (
    <div className="min-h-screen bg-bg flex flex-col items-center justify-center p-8">
      <h1 className="text-4xl font-bold text-white mb-4">404 - Page Not Found</h1>
      <Link
        to="/"
        className="text-accent hover:underline text-sm font-medium"
      >
        Return to Repositories
      </Link>
    </div>
  );
};
