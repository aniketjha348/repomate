import type { Evidence, EvidenceKind } from "@/lib/types";
import { cn } from "@/lib/utils";

const KIND_STYLES: Record<EvidenceKind, string> = {
  ISSUE: "border-sky-500/30 bg-sky-500/10 text-sky-400",
  DOC: "border-violet-500/30 bg-violet-500/10 text-violet-400",
  SOURCE: "border-emerald-500/30 bg-emerald-500/10 text-emerald-400",
  TEST: "border-amber-500/30 bg-amber-500/10 text-amber-400",
  METADATA: "border-zinc-600/40 bg-zinc-700/20 text-zinc-400",
};

function Snippet({ evidence }: { evidence: Evidence }) {
  const lines = evidence.snippet.replace(/\n$/, "").split("\n");
  const numbered = typeof evidence.start_line === "number";
  return (
    <pre className="overflow-x-auto rounded-md border border-border bg-background/60 p-3 font-mono text-xs leading-relaxed text-foreground/90 scrollbar-thin">
      {lines.map((line, index) => (
        <span key={index} className="block whitespace-pre">
          {numbered ? (
            <span className="mr-3 inline-block w-8 shrink-0 select-none text-right text-muted-foreground/50">
              {(evidence.start_line as number) + index}
            </span>
          ) : null}
          {line}
        </span>
      ))}
    </pre>
  );
}

export function EvidenceItem({ evidence }: { evidence: Evidence }) {
  const { start_line: start, end_line: end } = evidence;
  const range =
    typeof start === "number"
      ? `:${start}${typeof end === "number" ? `-${end}` : ""}`
      : "";

  return (
    <li className="space-y-2 rounded-lg border border-border bg-card/60 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <span
          className={cn(
            "inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
            KIND_STYLES[evidence.kind] ?? KIND_STYLES.METADATA,
          )}
        >
          {evidence.kind}
        </span>
        <code className="min-w-0 break-all font-mono text-xs text-foreground">
          {evidence.path}
          <span className="text-muted-foreground">{range}</span>
        </code>
      </div>
      <p className="text-xs leading-relaxed text-muted-foreground">
        {evidence.rationale}
      </p>
      {evidence.snippet ? <Snippet evidence={evidence} /> : null}
    </li>
  );
}
