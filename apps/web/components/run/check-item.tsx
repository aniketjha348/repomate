import { StatusBadge } from "./status-badge";
import type { VerificationCheck } from "@/lib/types";

/** One verification check row with collapsible command output. */
export function CheckItem({ check }: { check: VerificationCheck }) {
  return (
    <li className="rounded-lg border border-border bg-card/60 p-4">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <StatusBadge status={check.status} />
        <span className="text-sm font-medium text-foreground">
          {check.name}
        </span>
        {typeof check.exit_code === "number" ? (
          <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-xs text-muted-foreground">
            exit {check.exit_code}
          </code>
        ) : null}
      </div>

      {check.command ? (
        <pre className="mt-3 overflow-x-auto rounded-md border border-border bg-background/60 p-2.5 font-mono text-xs text-foreground/85 scrollbar-thin">
          <span className="select-none text-muted-foreground/60">$ </span>
          {check.command}
        </pre>
      ) : null}

      {check.status === "NOT_RUN" && check.reason ? (
        <p className="mt-2 text-xs leading-relaxed text-amber-400/90">
          {check.reason}
        </p>
      ) : null}

      {check.output_tail ? (
        <details className="mt-3 text-xs">
          <summary className="cursor-pointer select-none text-muted-foreground hover:text-foreground">
            Output tail
          </summary>
          <pre className="mt-2 max-h-64 overflow-auto rounded-md border border-border bg-background/60 p-2.5 font-mono leading-relaxed text-muted-foreground scrollbar-thin">
            {check.output_tail}
          </pre>
        </details>
      ) : null}
    </li>
  );
}
