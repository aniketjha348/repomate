import { EvidenceItem } from "./evidence-item";
import type { Evidence } from "@/lib/types";

export function EvidencePanel({ evidence }: { evidence: Evidence[] }) {
  if (evidence.length === 0) {
    return (
      <p className="rounded-xl border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
        No evidence gathered yet.
      </p>
    );
  }

  return (
    <ul className="space-y-3">
      {evidence.map((item) => (
        <EvidenceItem key={item.id} evidence={item} />
      ))}
    </ul>
  );
}
