import { Badge } from "@/components/ui/badge";
import type { GroundingReport, Plan } from "@/lib/types";
import { cn } from "@/lib/utils";

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <p className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
      {children}
    </p>
  );
}

function ChangeTypeBadge({ changeType }: { changeType: string }) {
  const isCreate = changeType === "CREATE";
  return (
    <span
      className={cn(
        "shrink-0 rounded border px-1.5 py-0.5 font-mono text-[10px] font-medium",
        isCreate
          ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-400"
          : "border-sky-500/30 bg-sky-500/10 text-sky-400",
      )}
    >
      {changeType}
    </span>
  );
}

function GroundingPanel({ grounding }: { grounding: GroundingReport }) {
  const unresolved = grounding.unresolved_evidence_ids;
  const hypotheses = grounding.claims.filter(
    (claim) => claim.support_status === "hypothesis",
  );
  const clean = unresolved.length === 0 && hypotheses.length === 0;

  return (
    <div
      className={cn(
        "rounded-lg border p-4",
        clean
          ? "border-emerald-500/30 bg-emerald-500/5"
          : "border-amber-500/30 bg-amber-500/5",
      )}
    >
      <SectionLabel>Evidence grounding</SectionLabel>
      <p className="text-sm text-foreground/90">
        {grounding.claims.length} claim(s):{" "}
        <span className="text-emerald-400">
          {grounding.claims.length - hypotheses.length} supported
        </span>
        {hypotheses.length > 0 ? (
          <>
            {", "}
            <span className="text-amber-400">
              {hypotheses.length} hypothesis
            </span>
          </>
        ) : null}
        . {grounding.resolved_evidence_ids.length} citation(s) resolved
        {unresolved.length > 0 ? (
          <>
            ,{" "}
            <span className="text-amber-400">
              {unresolved.length} unresolved
            </span>
          </>
        ) : null}
        .
      </p>

      {hypotheses.length > 0 ? (
        <ul className="mt-3 space-y-1.5">
          {hypotheses.map((claim) => (
            <li
              key={claim.text}
              className="flex items-start gap-2 text-xs leading-relaxed text-amber-200/90"
            >
              <span
                aria-hidden
                className="mt-0.5 shrink-0 rounded border border-amber-500/40 px-1 font-mono text-[10px] text-amber-400"
              >
                HYPOTHESIS
              </span>
              <span className="min-w-0 break-words">{claim.text}</span>
            </li>
          ))}
        </ul>
      ) : null}

      {unresolved.length > 0 ? (
        <p className="mt-3 text-xs text-amber-300/80">
          Unresolved references (not verified citations):{" "}
          <code className="font-mono">{unresolved.join(", ")}</code>
        </p>
      ) : null}

      {grounding.warnings.length > 0 ? (
        <ul className="mt-3 space-y-1">
          {grounding.warnings.map((warning, index) => (
            <li
              key={`${warning.code}-${warning.evidence_id}-${index}`}
              className="text-[11px] leading-relaxed text-muted-foreground"
            >
              <code className="font-mono text-amber-400/80">
                {warning.code}
              </code>{" "}
              {warning.message}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

export function PlanPanel({
  plan,
  grounding,
}: {
  plan: Plan;
  grounding?: GroundingReport | null;
}) {
  // Acceptance criteria are only ticked when the grounding verdict backs
  // them. An unvalidated criterion is shown as unverified, never as met.
  const supportedTexts = new Set(
    (grounding?.claims ?? [])
      .filter((claim) => claim.support_status === "supported")
      .map((claim) => claim.text),
  );
  const hasGrounding = Boolean(grounding);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-2">
        <Badge className="bg-sky-500/15 text-sky-400">
          {plan.task_type}
        </Badge>
        <span className="font-mono text-xs text-muted-foreground">
          planned by {plan.planned_by}
        </span>
      </div>

      <p className="text-sm leading-relaxed text-foreground/90">
        {plan.summary}
      </p>

      {plan.planned_changes.length > 0 ? (
        <div>
          <SectionLabel>Planned changes</SectionLabel>
          <ul className="space-y-2">
            {plan.planned_changes.map((change) => (
              <li
                key={change.path}
                className="flex flex-wrap items-baseline gap-x-2 gap-y-1 rounded-lg border border-border bg-card/60 px-3 py-2"
              >
                <ChangeTypeBadge changeType={change.change_type} />
                <code className="min-w-0 break-all font-mono text-xs text-foreground">
                  {change.path}
                </code>
                <span className="basis-full pl-0 text-xs text-muted-foreground sm:basis-auto">
                  {change.rationale}
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {plan.acceptance_criteria.length > 0 ? (
        <div>
          <SectionLabel>Acceptance criteria</SectionLabel>
          <ul className="space-y-1.5">
            {plan.acceptance_criteria.map((criterion) => {
              const verified = supportedTexts.has(criterion);
              const unverified = hasGrounding && !verified;
              return (
                <li
                  key={criterion}
                  className="flex items-start gap-2 text-sm text-foreground/90"
                >
                  <span
                    aria-hidden
                    className={cn(
                      "mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded border text-[10px]",
                      verified
                        ? "border-emerald-500/40 text-emerald-400"
                        : "border-muted-foreground/40 text-muted-foreground",
                    )}
                  >
                    {verified ? "✓" : "?"}
                  </span>
                  <span className={cn(unverified && "text-muted-foreground")}>
                    {criterion}
                    {unverified ? (
                      <span className="ml-1.5 font-mono text-[10px] uppercase tracking-wide text-amber-400/80">
                        unverified
                      </span>
                    ) : null}
                  </span>
                </li>
              );
            })}
          </ul>
        </div>
      ) : null}

      {grounding ? <GroundingPanel grounding={grounding} /> : null}

      {plan.need_more_info && plan.questions.length > 0 ? (
        <div className="rounded-lg border border-sky-500/30 bg-sky-500/5 p-4">
          <SectionLabel>Needs more info</SectionLabel>
          <ul className="list-inside list-disc space-y-1.5 text-sm text-sky-200/90">
            {plan.questions.map((question) => (
              <li key={question}>{question}</li>
            ))}
          </ul>
          <p className="mt-3 text-xs text-muted-foreground">
            No patch was generated because the plan needs these answers first.
          </p>
        </div>
      ) : null}

      {plan.limitations.length > 0 ? (
        <div>
          <SectionLabel>Limitations</SectionLabel>
          <ul className="space-y-1.5">
            {plan.limitations.map((limitation) => (
              <li
                key={limitation}
                className="flex items-start gap-2 text-xs leading-relaxed text-amber-400/90"
              >
                <span aria-hidden className="mt-1 h-1 w-1 shrink-0 rounded-full bg-amber-400/70" />
                {limitation}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}
