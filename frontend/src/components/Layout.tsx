import React from "react";
import { Outlet } from "react-router-dom";
import { Header } from "./Header";
import { LeftNav } from "./LeftNav";
import { Footer } from "./Footer";

export const Layout: React.FC = () => {
  return (
    <div className="min-h-screen bg-bg text-gray-100 flex flex-col font-sans">
      <Header />
      <div className="flex-1 flex min-h-0">
        <LeftNav />
        <div className="flex-1 flex flex-col min-w-0">
          <main className="flex-1">
            <Outlet />
          </main>
          <Footer />
        </div>
      </div>
    </div>
  );
};

export default Layout;
