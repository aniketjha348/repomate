"use client";

import * as React from "react";
import type { RunRecord } from "@/lib/types";
import { formatDate } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { PlannerChip } from "./planner-chip";
import { StatusBadge } from "./status-badge";

export function RunHeader({ record }: { record: RunRecord }) {
  const [copied, setCopied] = React.useState(false);
  const planner = record.planner || record.plan?.planned_by;

  async function copyRunId() {
    try {
      await navigator.clipboard.writeText(record.run_id);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // clipboard unavailable; ignore
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <StatusBadge status={record.status} className="px-3 py-1 text-sm" />
        <PlannerChip planner={planner} />
      </div>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 font-mono text-xs text-muted-foreground">
        <span className="inline-flex items-center gap-1">
          {record.run_id}
          <Button
            variant="ghost"
            size="sm"
            onClick={copyRunId}
            aria-label="Copy run id"
            className="h-6 px-1.5 text-[10px]"
          >
            {copied ? "copied ✓" : "copy"}
          </Button>
        </span>
        <span>created {formatDate(record.created_at)}</span>
        <span>updated {formatDate(record.updated_at)}</span>
      </div>
    </div>
  );
}
