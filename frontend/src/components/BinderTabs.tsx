export interface BinderTab {
  key: string;
  label: string;
  ready: boolean;
}

/** Numbered section navigation: a vertical rail on desktop, a scrolling strip on phones.
 *
 *  A section whose stage has not run is marked, not hidden: the shape of the
 *  pipeline stays visible.
 */
export default function BinderTabs({
  tabs,
  active,
  onSelect,
}: {
  tabs: BinderTab[];
  active: string;
  onSelect: (key: string) => void;
}) {
  return (
    <nav aria-label="Analysis sections" className="-mx-4 overflow-x-auto px-4 md:mx-0 md:overflow-visible md:px-0">
      <ol className="flex gap-1 md:flex-col">
        {tabs.map((tab, index) => (
          <li key={tab.key} className="shrink-0">
            <button
              type="button"
              onClick={() => onSelect(tab.key)}
              aria-current={tab.key === active ? "page" : undefined}
              className={`nav-item w-full ${tab.key === active ? "nav-item-active" : ""}`}
            >
              <span className="nav-index">{String(index + 1).padStart(2, "0")}</span>
              <span className="flex-1 text-left">{tab.label}</span>
              {!tab.ready && (
                <span className="size-1.5 rounded-full border border-border-strong" title="Not yet computed">
                  <span className="sr-only">not yet computed</span>
                </span>
              )}
            </button>
          </li>
        ))}
      </ol>
    </nav>
  );
}
