import { Link, Route, Routes } from "react-router-dom";

import CompanyDetail from "./pages/CompanyDetail";
import Dashboard from "./pages/Dashboard";
import Methodology from "./pages/Methodology";
import NewCompany from "./pages/NewCompany";

export default function App() {
  return (
    <div className="mx-auto min-h-screen max-w-6xl px-5 py-8">
      <header className="mb-8 flex flex-wrap items-end justify-between gap-3 border-b border-edge pb-5">
        <div>
          <Link to="/" className="text-xl font-semibold tracking-tight text-slate-100">
            FinSight<span className="text-accent"> 360</span>
          </Link>
          <p className="mt-1 text-xs text-muted">
            Ratio engine · Altman Z / Z&prime; / Z&Prime; · weighted health score · narrated,
            not decided, by an LLM
          </p>
        </div>
        <nav className="flex gap-2 text-sm">
          <Link to="/" className="text-muted hover:text-accent">
            Companies
          </Link>
          <span className="text-edge">/</span>
          <Link to="/methodology" className="text-muted hover:text-accent">
            Methodology
          </Link>
        </nav>
      </header>

      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/new" element={<NewCompany />} />
        <Route path="/methodology" element={<Methodology />} />
        <Route path="/companies/:companyId" element={<CompanyDetail />} />
        <Route
          path="*"
          element={
            <p className="panel p-6 text-sm text-muted">
              Nothing here.{" "}
              <Link to="/" className="text-accent">
                Back to companies
              </Link>
            </p>
          }
        />
      </Routes>
    </div>
  );
}
