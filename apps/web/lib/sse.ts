import { API_URL } from "./config";
import type { RunEvent } from "./types";

/**
 * Union event groups by seq, sorted ascending — used to merge server
 * snapshots with live SSE events without duplicates.
 */
export function mergeEvents(groups: RunEvent[][]): RunEvent[] {
  const bySeq = new Map<number, RunEvent>();
  for (const group of groups) {
    for (const event of group) {
      if (!bySeq.has(event.seq)) bySeq.set(event.seq, event);
    }
  }
  return [...bySeq.values()].sort((a, b) => a.seq - b.seq);
}

/**
 * Subscribe to the run's live event stream.
 * "progress" events carry a RunEvent JSON payload; "done" marks the end.
 * Returns a cleanup function that closes the connection.
 */
export function subscribeRunEvents(
  runId: string,
  onEvent: (event: RunEvent) => void,
  onDone: () => void,
): () => void {
  const source = new EventSource(
    `${API_URL}/api/runs/${encodeURIComponent(runId)}/events`,
  );

  source.addEventListener("progress", (event) => {
    try {
      onEvent(JSON.parse((event as MessageEvent<string>).data) as RunEvent);
    } catch {
      // malformed frame; skip rather than kill the stream
    }
  });

  source.addEventListener("done", () => {
    onDone();
  });

  // EventSource reconnects automatically on transient errors; nothing to do.
  return () => source.close();
}
