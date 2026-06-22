import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, NavLink, Route, Routes, useLocation } from "react-router-dom";
import AdminPage from "./pages/AdminPage";
import CustomerPage from "./pages/CustomerPage";
import "./styles.css";

function AppHeader() {
  const { pathname } = useLocation();
  const customerActive = pathname === "/" || pathname.startsWith("/chat/");

  return (
    <header className="app-header">
      <div className="app-brand">
        <span className="brand-mark" aria-hidden />
        <div>
          <h1>Retail Kiosk</h1>
          <p className="brand-tag">Moorcheh Edge demo</p>
        </div>
      </div>
      <nav className="app-nav">
        <NavLink
          to="/"
          className={() => (customerActive ? "nav-link active" : "nav-link")}
        >
          Customer
        </NavLink>
        <NavLink to="/admin" className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}>
          Admin
        </NavLink>
      </nav>
    </header>
  );
}

function App() {
  return (
    <BrowserRouter>
      <div className="app-shell">
        <AppHeader />
        <main className="app-main app-main--wide">
          <Routes>
            <Route path="/" element={<CustomerPage />} />
            <Route path="/chat/:conversationId" element={<CustomerPage />} />
            <Route path="/admin" element={<AdminPage />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
