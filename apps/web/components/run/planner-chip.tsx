import { cn } from "@/lib/utils";

/** Shows which planner produced the plan; flags offline heuristic mode. */
export function PlannerChip({
  planner,
  className,
}: {
  planner: string | null | undefined;
  className?: string;
}) {
  if (!planner) return null;
  const isHeuristic = planner.toLowerCase().includes("heuristic");
  return (
    <span className={cn("inline-flex flex-wrap items-center gap-2", className)}>
      <span className="inline-flex items-center rounded-md border border-border bg-muted px-2 py-0.5 font-mono text-xs text-muted-foreground">
        planner: {planner}
      </span>
      {isHeuristic ? (
        <span className="text-xs text-amber-400/90">
          offline heuristic planner — set VYCE_API_KEY for model planning
        </span>
      ) : null}
    </span>
  );
}
