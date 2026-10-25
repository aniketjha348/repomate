import { Badge } from "@/components/ui/badge";
import type { Plan } from "@/lib/types";
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

export function PlanPanel({ plan }: { plan: Plan }) {
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
            {plan.acceptance_criteria.map((criterion) => (
              <li
                key={criterion}
                className="flex items-start gap-2 text-sm text-foreground/90"
              >
                <span
                  aria-hidden
                  className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded border border-emerald-500/40 text-[10px] text-emerald-400"
                >
                  ✓
                </span>
                {criterion}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

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
