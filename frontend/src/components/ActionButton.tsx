import { Loader2 } from "lucide-react";
import type { ReactNode } from "react";

/**
 * A button that shows its own spinner while its request runs.
 *
 * `busy` is this button's request; `disabled` covers any other request in
 * flight, so two writes to the same company never race.
 */
export default function ActionButton({
  busy,
  disabled,
  onClick,
  children,
  busyLabel,
  variant = "primary",
  type = "button",
}: {
  busy?: boolean;
  disabled?: boolean;
  onClick?: () => void;
  children: ReactNode;
  busyLabel: string;
  variant?: "primary" | "secondary";
  type?: "button" | "submit";
}) {
  return (
    <button
      type={type}
      className={variant === "primary" ? "btn-primary" : "btn-secondary"}
      disabled={busy || disabled}
      onClick={onClick}
      aria-busy={busy || undefined}
    >
      {busy && <Loader2 size={14} strokeWidth={1.5} className="animate-spin" aria-hidden />}
      {busy ? busyLabel : children}
    </button>
  );
}
