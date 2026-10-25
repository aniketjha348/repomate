import { cn } from "@/lib/utils";

/** Shared status vocabulary across run, events and verification checks. */
const STATUS_STYLES: Record<string, string> = {
  PENDING: "border-amber-500/30 bg-amber-500/10 text-amber-400",
  RUNNING: "border-amber-500/30 bg-amber-500/10 text-amber-400",
  STARTED: "border-amber-500/30 bg-amber-500/10 text-amber-400",
  COMPLETED: "border-emerald-500/30 bg-emerald-500/10 text-emerald-400",
  PASSED: "border-emerald-500/30 bg-emerald-500/10 text-emerald-400",
  NEED_MORE_INFO: "border-sky-500/30 bg-sky-500/10 text-sky-400",
  INFO: "border-sky-500/30 bg-sky-500/10 text-sky-400",
  FAILED: "border-red-500/30 bg-red-500/10 text-red-400",
  NOT_RUN: "border-zinc-600/40 bg-zinc-700/20 text-zinc-400",
  CANCELLED: "border-zinc-600/40 bg-zinc-700/20 text-zinc-400",
};

const PULSING = new Set(["PENDING", "RUNNING", "STARTED"]);

export function StatusBadge({
  status,
  className,
}: {
  status: string;
  className?: string;
}) {
  const style = STATUS_STYLES[status] ?? STATUS_STYLES.NOT_RUN;
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium leading-none",
        style,
        className,
      )}
    >
      {PULSING.has(status) ? (
        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-current" />
      ) : null}
      {status.replaceAll("_", " ")}
    </span>
  );
}
