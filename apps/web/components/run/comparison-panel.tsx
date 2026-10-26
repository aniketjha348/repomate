import { StatusBadge } from "./status-badge";
import type { VerificationComparison, VerificationRun } from "@/lib/types";
import { cn, formatDuration } from "@/lib/utils";

const OUTCOME_NOTE_STYLES: Record<string, string> = {
  CONSISTENT_IMPROVEMENT: "border-emerald-500/30 bg-emerald-500/5 text-emerald-200/90",
  NO_REGRESSION_DETECTED: "border-emerald-500/30 bg-emerald-500/5 text-emerald-200/90",
  UNRESOLVED: "border-amber-500/30 bg-amber-500/5 text-amber-200/90",
  POTENTIAL_REGRESSION: "border-red-500/30 bg-red-500/5 text-red-200/90",
  BASELINE_INCOMPLETE: "border-zinc-600/40 bg-zinc-700/10 text-zinc-300",
  POST_PATCH_INCOMPLETE: "border-zinc-600/40 bg-zinc-700/10 text-zinc-300",
};

function RunSummary({ label, run }: { label: string; run: VerificationRun }) {
  return (
    <div className="rounded-md border border-border bg-background/40 p-3">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1.5">
        <StatusBadge status={run.status} />
        <span className="text-sm font-medium text-foreground">{label}</span>
        <span className="font-mono text-xs text-muted-foreground">
          {typeof run.exit_code === "number" ? `exit ${run.exit_code}` : "not run"}
        </span>
        <span className="text-xs text-muted-foreground">
          {formatDuration(run.duration_ms)}
        </span>
      </div>

      {run.command ? (
        <pre className="mt-2 overflow-x-auto rounded border border-border bg-background/60 px-2 py-1.5 font-mono text-xs text-foreground/85 scrollbar-thin">
          <span className="select-none text-muted-foreground/60">$ </span>
          {run.command}
        </pre>
      ) : null}

      {run.status === "NOT_RUN" && run.reason ? (
        <p className="mt-2 text-xs leading-relaxed text-amber-400/90">
          {run.reason}
        </p>
      ) : null}

      {run.output_summary ? (
        <details className="mt-2 text-xs">
          <summary className="cursor-pointer select-none text-muted-foreground hover:text-foreground">
            Output summary
          </summary>
          <pre className="mt-2 max-h-56 overflow-auto rounded border border-border bg-background/60 p-2 font-mono leading-relaxed text-muted-foreground scrollbar-thin">
            {run.output_summary}
          </pre>
        </details>
      ) : null}
    </div>
  );
}

/** Deterministic baseline vs post-patch evidence, never a "verified fix" claim. */
export function ComparisonPanel({
  comparison,
  resolutionStatement,
}: {
  comparison: VerificationComparison;
  resolutionStatement?: string;
}) {
  const noteStyle =
    OUTCOME_NOTE_STYLES[comparison.outcome] ?? OUTCOME_NOTE_STYLES.BASELINE_INCOMPLETE;

  return (
    <section className="space-y-3 rounded-lg border border-border bg-card/60 p-4">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <h3 className="text-sm font-medium text-foreground">
          Baseline vs post-patch
        </h3>
        <StatusBadge status={comparison.outcome} />
      </div>

      <p className="text-xs leading-relaxed text-muted-foreground">
        {comparison.interpretation}
        {comparison.commands_match === false
          ? " The two runs did not execute the same command, so this comparison is incomplete."
          : null}
      </p>

      <div className="grid gap-3 sm:grid-cols-2">
        <RunSummary label="Clean baseline" run={comparison.baseline} />
        <RunSummary label="Patched workspace" run={comparison.post_patch} />
      </div>

      <p className="font-mono text-[11px] leading-relaxed text-muted-foreground/80">
        base commit: {comparison.base_commit.slice(0, 12)} · patch sha256:{" "}
        {comparison.patch_sha256.slice(0, 12)}
      </p>

      {resolutionStatement ? (
        <p className={cn("rounded-md border px-3 py-2 text-xs leading-relaxed", noteStyle)}>
          {resolutionStatement}
        </p>
      ) : null}
    </section>
  );
}
