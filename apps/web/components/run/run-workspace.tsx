"use client";

import * as React from "react";
import Link from "next/link";
import { getRun } from "@/lib/api-client";
import { mergeEvents, subscribeRunEvents } from "@/lib/sse";
import type { RunEvent, RunRecord } from "@/lib/types";
import { buttonClasses } from "@/components/ui/button";
import { ErrorBanner } from "./error-banner";
import { EventsFeed } from "./events-feed";
import { EvidencePanel } from "./evidence-panel";
import { OrientationCard } from "./orientation-card";
import { PlanPanel } from "./plan-panel";
import { RunHeader } from "./run-header";
import { Section } from "./section";
import { SnapshotCard } from "./snapshot-card";
import { TestGuidancePanel } from "./test-guidance";
import { DiffViewer } from "./diff-viewer";
import { VerificationPanel } from "./verification-panel";

const POLL_INTERVAL_MS = 2000;

export function RunWorkspace({ runId }: { runId: string }) {
  const [record, setRecord] = React.useState<RunRecord | null>(null);
  const [events, setEvents] = React.useState<RunEvent[]>([]);
  const [loadError, setLoadError] = React.useState<string | null>(null);

  const fetchRecord = React.useCallback(async () => {
    try {
      const next = await getRun(runId);
      setRecord(next);
      setEvents((prev) => mergeEvents([next.events, prev]));
      setLoadError(null);
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : "Failed to load run");
    }
  }, [runId]);

  React.useEffect(() => {
    setRecord(null);
    setEvents([]);
    void fetchRecord();
  }, [fetchRecord]);

  const active =
    record === null
      ? loadError === null
      : record.status === "PENDING" || record.status === "RUNNING";

  // Poll while the run is in flight (SSE may be blocked by proxies).
  React.useEffect(() => {
    if (!active) return;
    const id = setInterval(() => void fetchRecord(), POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [active, fetchRecord]);

  // Live events via SSE; "done" triggers a final authoritative refetch.
  React.useEffect(() => {
    if (!active) return;
    return subscribeRunEvents(
      runId,
      (event) =>
        setEvents((prev) =>
          prev.some((e) => e.seq === event.seq)
            ? prev
            : mergeEvents([prev, [event]]),
        ),
      () => void fetchRecord(),
    );
  }, [active, runId, fetchRecord]);

  if (!record) {
    if (loadError) {
      return (
        <div className="space-y-4 rounded-xl border border-red-500/30 bg-red-500/10 p-6">
          <p className="text-sm font-medium text-red-300">{loadError}</p>
          <Link href="/" className={buttonClasses("outline", "sm")}>
            Start a new run
          </Link>
        </div>
      );
    }
    return (
      <p className="animate-pulse text-sm text-muted-foreground">
        Loading run {runId}…
      </p>
    );
  }

  return (
    <div className="space-y-6">
      <RunHeader record={record} />
      {record.error ? <ErrorBanner error={record.error} /> : null}
      {record.snapshot ? <SnapshotCard snapshot={record.snapshot} /> : null}
      {record.orientation ? (
        <OrientationCard orientation={record.orientation} />
      ) : null}
      {record.test_guidance ? (
        <TestGuidancePanel guidance={record.test_guidance} />
      ) : null}
      <EventsFeed events={events} defaultOpen={active} />
      <Section title={`Evidence (${record.evidence.length})`}>
        <EvidencePanel evidence={record.evidence} />
      </Section>
      {record.plan ? (
        <Section title="Contribution plan">
          <PlanPanel plan={record.plan} />
        </Section>
      ) : null}
      {record.artifact ? (
        <Section title="Patch">
          <DiffViewer runId={runId} artifact={record.artifact} />
        </Section>
      ) : record.status === "NEED_MORE_INFO" ? (
        <Section title="Patch">
          <p className="rounded-lg border border-dashed border-sky-500/30 bg-sky-500/5 p-6 text-center text-sm text-sky-300/90">
            No patch yet — the plan needs more information before RepoMate can
            generate one.
          </p>
        </Section>
      ) : null}
      {record.receipt ? (
        <Section title="Verification">
          <VerificationPanel receipt={record.receipt} />
        </Section>
      ) : null}
    </div>
  );
}
