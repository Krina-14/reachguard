import React from "react";
import { useParams } from "react-router-dom";

export const RepoDetailPage: React.FC = () => {
  const { repoId } = useParams<{ repoId: string }>();

  return (
    <div className="min-h-screen bg-bg p-8">
      <div className="max-w-7xl mx-auto">
        <h1 className="text-3xl font-bold text-white mb-4">
          Repository {repoId}
        </h1>
      </div>
    </div>
  );
};
