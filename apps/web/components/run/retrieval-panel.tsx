import { StatusBadge } from "./status-badge";
import type { RetrievalLimitHit, RetrievalReport } from "@/lib/types";
import { formatBytes, formatDuration } from "@/lib/utils";

function allowedLabel(hit: RetrievalLimitHit): string {
  if (hit.limit === "MAX_SECONDS") return `${hit.allowed}s`;
  if (hit.limit === "MAX_BYTES_PER_FILE" || hit.limit === "MAX_TOTAL_BYTES") {
    return formatBytes(hit.allowed);
  }
  return String(hit.allowed);
}

function observedLabel(hit: RetrievalLimitHit): string {
  if (hit.limit === "MAX_SECONDS") return `${hit.observed}s`;
  if (hit.limit === "MAX_BYTES_PER_FILE" || hit.limit === "MAX_TOTAL_BYTES") {
    return formatBytes(hit.observed);
  }
  return String(hit.observed);
}

/** Proof of how much of the repository retrieval actually examined. */
export function RetrievalPanel({ retrieval }: { retrieval: RetrievalReport }) {
  const partial = retrieval.status === "PARTIAL";

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <StatusBadge status={retrieval.status} />
        <span className="text-sm font-medium text-foreground">
          Retrieval scope
        </span>
        <span className="font-mono text-xs text-muted-foreground">
          {retrieval.files_examined}/{retrieval.files_eligible} eligible files ·{" "}
          {formatBytes(retrieval.bytes_read)} · {retrieval.search_results} matches
        </span>
      </div>

      <p
        className={
          partial
            ? "rounded-md border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-xs leading-relaxed text-amber-200/90"
            : "text-xs leading-relaxed text-muted-foreground"
        }
      >
        {retrieval.summary}
      </p>

      {partial ? (
        <ul className="space-y-2">
          {retrieval.limit_hits.map((hit) => (
            <li
              key={hit.limit}
              className="rounded-md border border-amber-500/20 bg-amber-500/5 px-3 py-2"
            >
              <p className="font-mono text-xs text-amber-300/90">
                {hit.limit}: {observedLabel(hit)} / {allowedLabel(hit)} allowed
              </p>
              <p className="mt-1 text-xs leading-relaxed text-amber-200/80">
                {hit.remaining_work}
              </p>
            </li>
          ))}
        </ul>
      ) : null}

      <p className="font-mono text-[11px] text-muted-foreground/80">
        limits: {retrieval.limits.max_files} files ·{" "}
        {formatBytes(retrieval.limits.max_bytes_per_file)}/file ·{" "}
        {formatBytes(retrieval.limits.max_total_bytes)} total ·{" "}
        {retrieval.limits.max_search_results} results ·{" "}
        {retrieval.limits.max_seconds}s · elapsed{" "}
        {formatDuration(retrieval.elapsed_ms)}
      </p>
    </div>
  );
}
