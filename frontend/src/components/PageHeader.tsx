import type { ReactNode } from "react";

/**
 * The top of every page: a mono eyebrow, a serif headline that states the claim
 * (wrap one word in <em> for the italic emphasis), a short summary and the page's
 * single primary action on the right.
 */
export default function PageHeader({
  eyebrow,
  title,
  summary,
  actions,
  children,
}: {
  eyebrow?: ReactNode;
  title: ReactNode;
  summary?: ReactNode;
  actions?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <header className="border-b border-border pb-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          {eyebrow && <p className="section-no">{eyebrow}</p>}
          <h1 className="display mt-2 text-4xl text-foreground sm:text-5xl">{title}</h1>
          {summary && (
            <p className="prose-measure mt-3 text-sm leading-relaxed text-muted-foreground">{summary}</p>
          )}
        </div>
        {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      </div>
      {children}
    </header>
  );
}
