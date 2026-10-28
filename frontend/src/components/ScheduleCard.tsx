import type { ReactNode } from "react";

/** One numbered schedule sheet. The number is how a reviewer cross-references it. */
export default function ScheduleCard({
  reference,
  title,
  aside,
  note,
  children,
}: {
  reference?: string;
  title: ReactNode;
  aside?: ReactNode;
  note?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <section className="sheet min-w-0">
      <header className="sheet-head">
        <div className="min-w-0">
          {reference && <p className="section-no">{reference}</p>}
          <h2 className="sheet-title mt-0.5">{title}</h2>
        </div>
        {aside && <div className="flex flex-wrap items-center gap-2">{aside}</div>}
      </header>
      {children}
      {note && <div className="sheet-note border-t border-border">{note}</div>}
    </section>
  );
}
