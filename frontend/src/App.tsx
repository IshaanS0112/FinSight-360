import { Suspense, lazy } from "react";
import { Link, Route, Routes, useLocation } from "react-router-dom";

import { EmptyState, LoadingBlock } from "./components/States";

// One chunk per page: the index never downloads the Portfolio Lab charts.
const Dashboard = lazy(() => import("./pages/Dashboard"));
const CompanyDetail = lazy(() => import("./pages/CompanyDetail"));
const NewCompany = lazy(() => import("./pages/NewCompany"));
const PortfolioLab = lazy(() => import("./pages/PortfolioLab"));
const Methodology = lazy(() => import("./pages/Methodology"));

const NAV = [
  { to: "/", label: "Companies", section: ["/", "/companies", "/new"] },
  { to: "/portfolio", label: "Portfolio Lab", section: ["/portfolio"] },
  { to: "/methodology", label: "Methodology", section: ["/methodology"] },
];

/** A section owns its own path and everything under it; "/" owns only itself. */
function inSection(pathname: string, prefixes: string[]): boolean {
  return prefixes.some((prefix) => (prefix === "/" ? pathname === "/" : pathname.startsWith(prefix)));
}

export default function App() {
  const { pathname } = useLocation();
  return (
    <div className="min-h-screen">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-20 focus:rounded-md focus:bg-card focus:px-3 focus:py-2">
        Skip to content
      </a>
      <header className="border-b border-border bg-background">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-x-6 gap-y-2 px-4 py-3 sm:px-6">
          <Link to="/" className="display rounded-sm text-2xl text-foreground focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-ring">
            FinSight <em>360</em>
          </Link>
          <nav aria-label="Primary" className="-mx-1 flex gap-1 overflow-x-auto px-1">
            {NAV.map((item) => (
              <Link
                key={item.to}
                to={item.to}
                aria-current={inSection(pathname, item.section) ? "page" : undefined}
                className={`nav-item ${inSection(pathname, item.section) ? "nav-item-active" : ""}`}
              >
                {item.label}
              </Link>
            ))}
          </nav>
        </div>
      </header>

      <main id="main" className="mx-auto max-w-7xl px-4 py-8 sm:px-6">
        <Suspense fallback={<LoadingBlock rows={6} label="Loading page" />}>
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/new" element={<NewCompany />} />
            <Route path="/portfolio" element={<PortfolioLab />} />
            <Route path="/methodology" element={<Methodology />} />
            <Route path="/companies/:companyId" element={<CompanyDetail />} />
            <Route
              path="*"
              element={
                <EmptyState title="Nothing at this address" action={<Link to="/" className="btn-secondary">Back to companies</Link>}>
                  The link may point at a company that was deleted.
                </EmptyState>
              }
            />
          </Routes>
        </Suspense>
      </main>

      <footer className="border-t border-border">
        <p className="mx-auto max-w-7xl px-4 py-6 text-xs text-muted-foreground sm:px-6">
          Every figure on these pages is computed by deterministic code from sourced filings and prices. The
          language model only writes prose about them, and every number it writes is checked.
        </p>
      </footer>
    </div>
  );
}
