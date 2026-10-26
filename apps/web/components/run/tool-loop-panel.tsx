import { StatusBadge } from "./status-badge";
import type {
  ModelBudgetReport,
  ToolCallRecord,
  ToolLoopLimitHit,
  ToolLoopReport,
} from "@/lib/types";
import { formatBytes } from "@/lib/utils";

function allowedLabel(hit: ToolLoopLimitHit): string {
  if (hit.limit === "MAX_SECONDS") return `${hit.allowed}s`;
  if (hit.limit === "MAX_TOTAL_BYTES") return formatBytes(hit.allowed);
  return String(hit.allowed);
}

function observedLabel(hit: ToolLoopLimitHit): string {
  if (hit.limit === "MAX_SECONDS") return `${hit.observed}s`;
  if (hit.limit === "MAX_TOTAL_BYTES") return formatBytes(hit.observed);
  return String(hit.observed);
}

function CallRow({ call }: { call: ToolCallRecord }) {
  const statusClass =
    call.status === "OK"
      ? "text-emerald-400"
      : call.status === "REJECTED"
        ? "text-amber-400"
        : "text-red-400";

  return (
    <li className="rounded-md border border-border/60 bg-muted/20 px-3 py-2">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className="font-mono text-xs text-foreground">
          {call.index}. {call.tool}
        </span>
        {call.target ? (
          <span className="max-w-full truncate font-mono text-[11px] text-muted-foreground">
            {call.target}
          </span>
        ) : null}
        <span className={`ml-auto font-mono text-[11px] ${statusClass}`}>
          {call.status}
        </span>
        {call.bytes_read ? (
          <span className="font-mono text-[11px] text-muted-foreground">
            {formatBytes(call.bytes_read)}
          </span>
        ) : null}
      </div>
      {call.detail ? (
        <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
          {call.detail}
        </p>
      ) : null}
      {call.evidence_paths.length ? (
        <p className="mt-1 font-mono text-[11px] text-muted-foreground/80">
          evidence: {call.evidence_paths.join(", ")}
        </p>
      ) : null}
    </li>
  );
}

/** Bounded model research plus the run's actual model spend. */
export function ToolLoopPanel({
  report,
  usage,
}: {
  report?: ToolLoopReport | null;
  usage?: ModelBudgetReport | null;
}) {
  const partial = report?.status === "PARTIAL";

  return (
    <div className="space-y-4">
      {report ? (
        <>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
            <StatusBadge status={report.status} />
            <span className="text-sm font-medium text-foreground">
              Model-directed retrieval
            </span>
            <span className="font-mono text-xs text-muted-foreground">
              {report.model_calls} model calls · {report.tool_calls} tool calls ·{" "}
              {formatBytes(report.bytes_read)} · {report.records_added} evidence
              record(s) added
            </span>
          </div>

          <p
            className={
              partial
                ? "rounded-md border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-xs leading-relaxed text-amber-200/90"
                : "text-xs leading-relaxed text-muted-foreground"
            }
          >
            {report.summary}
          </p>

          {partial ? (
            <ul className="space-y-2">
              {report.limit_hits.map((hit) => (
                <li
                  key={hit.limit}
                  className="rounded-md border border-amber-500/20 bg-amber-500/5 px-3 py-2"
                >
                  <p className="font-mono text-xs text-amber-300/90">
                    {hit.limit}: {observedLabel(hit)} / {allowedLabel(hit)}{" "}
                    allowed
                  </p>
                  <p className="mt-1 text-xs leading-relaxed text-amber-200/80">
                    {hit.remaining_work}
                  </p>
                </li>
              ))}
            </ul>
          ) : null}

          {report.rejected_items ? (
            <p className="rounded-md border border-red-500/20 bg-red-500/5 px-3 py-2 text-xs leading-relaxed text-red-300/90">
              {report.rejected_items} retrieved item(s) were rejected by
              evidence validation and did not enter the evidence set.
            </p>
          ) : null}

          {report.calls.length ? (
            <ul className="space-y-2">
              {report.calls.map((call) => (
                <CallRow key={call.index} call={call} />
              ))}
            </ul>
          ) : null}

          <p className="font-mono text-[11px] text-muted-foreground/80">
            limits: {report.limits.max_tool_calls} tool calls ·{" "}
            {formatBytes(report.limits.max_total_bytes)} total ·{" "}
            {report.limits.max_seconds}s ·{" "}
            {report.limits.max_results_per_search} results/search · stop:{" "}
            {report.stop_reason || "—"}
          </p>
        </>
      ) : null}

      {usage ? (
        <div className="space-y-1 border-t border-border/60 pt-3">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <span className="text-sm font-medium text-foreground">
              Model usage
            </span>
            <span className="font-mono text-xs text-muted-foreground">
              {usage.calls}/{usage.limits.max_calls} calls ·{" "}
              {usage.total_tokens}/{usage.limits.max_tokens} tokens (prompt{" "}
              {usage.prompt_tokens}, completion {usage.completion_tokens})
            </span>
            <span className="font-mono text-[11px] text-muted-foreground/80">
              usage: {usage.usage_source}
            </span>
          </div>
          {usage.exhausted ? (
            <p className="text-xs leading-relaxed text-amber-300/90">
              {usage.reason}
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
