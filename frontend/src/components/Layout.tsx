import React from "react";
import { Outlet } from "react-router-dom";
import { Header } from "./Header";

export const Layout: React.FC = () => {
  return (
    <div className="min-h-screen bg-bg text-gray-100 flex flex-col font-sans">
      <Header />
      <main className="flex-1 flex flex-col">
        <Outlet />
      </main>
    </div>
  );
};
