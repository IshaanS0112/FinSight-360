import { AlertTriangle, RotateCw, X } from "lucide-react";
import type { ReactNode } from "react";

/** Skeleton lines shaped like the content that will replace them. */
export function LoadingBlock({ rows = 4, label = "Loading" }: { rows?: number; label?: string }) {
  return (
    <div className="sheet space-y-3 p-4" role="status" aria-label={label}>
      <div className="skeleton h-4 w-1/3" />
      {Array.from({ length: rows }, (_, index) => (
        <div key={index} className="skeleton h-3" style={{ width: `${92 - index * 9}%` }} />
      ))}
    </div>
  );
}

/** What this area will show once filled, and the one action that fills it. */
export function EmptyState({
  title,
  children,
  action,
}: {
  title: string;
  children?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="sheet px-6 py-10 text-center">
      <p className="text-base font-medium text-foreground">{title}</p>
      {children && (
        <div className="mx-auto mt-2 max-w-xl text-sm leading-relaxed text-muted-foreground">{children}</div>
      )}
      {action && <div className="mt-5 flex justify-center gap-2">{action}</div>}
    </div>
  );
}

/** A failed request: what happened in plain words, a retry, and the raw detail on request. */
export function ErrorState({
  title = "Something went wrong",
  message,
  onRetry,
}: {
  title?: string;
  message: string;
  onRetry?: () => void;
}) {
  return (
    <div className="callout-danger flex flex-wrap items-start gap-3" role="alert">
      <AlertTriangle size={16} strokeWidth={1.5} className="mt-0.5 shrink-0 text-destructive" aria-hidden />
      <div className="min-w-0 flex-1">
        <p className="font-medium">{title}</p>
        <details className="mt-1 text-xs text-muted-foreground">
          <summary className="cursor-pointer">Details</summary>
          <p className="mt-1 break-words font-mono">{message}</p>
        </details>
      </div>
      {onRetry && (
        <button type="button" className="btn-secondary" onClick={onRetry}>
          <RotateCw size={14} strokeWidth={1.5} aria-hidden />
          Retry
        </button>
      )}
    </div>
  );
}

/** A refusal or failed action, shown inline above the content it belongs to. */
export function InlineError({ message, onDismiss }: { message: string; onDismiss?: () => void }) {
  return (
    <div className="callout-danger flex items-start gap-3" role="alert">
      <AlertTriangle size={16} strokeWidth={1.5} className="mt-0.5 shrink-0 text-destructive" aria-hidden />
      <p className="min-w-0 flex-1 break-words">{message}</p>
      {onDismiss && (
        <button type="button" className="btn-quiet h-7" onClick={onDismiss} aria-label="Dismiss">
          <X size={14} strokeWidth={1.5} aria-hidden />
        </button>
      )}
    </div>
  );
}
