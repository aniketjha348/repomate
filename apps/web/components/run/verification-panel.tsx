import { CheckItem } from "./check-item";
import { StatusBadge } from "./status-badge";
import type { Receipt } from "@/lib/types";
import { formatDate } from "@/lib/utils";

export function VerificationPanel({ receipt }: { receipt: Receipt }) {
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-3">
        <StatusBadge status={receipt.overall} className="px-3 py-1 text-sm" />
        <span className="text-xs text-muted-foreground">
          {receipt.checks.filter((c) => c.status === "PASSED").length}/
          {receipt.checks.length} checks passed · {formatDate(receipt.created_at)}
        </span>
      </div>

      <ul className="space-y-3">
        {receipt.checks.map((check) => (
          <CheckItem key={check.name} check={check} />
        ))}
      </ul>

      <p className="font-mono text-xs text-muted-foreground">
        environment: {receipt.environment}
      </p>
      {receipt.limitations.length > 0 ? (
        <ul className="space-y-1">
          {receipt.limitations.map((limitation) => (
            <li key={limitation} className="text-xs text-muted-foreground/80">
              {limitation}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
