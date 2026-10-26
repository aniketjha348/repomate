"use client";

import * as React from "react";
import { StatusBadge } from "./status-badge";
import type { RunEvent } from "@/lib/types";
import { cn } from "@/lib/utils";

/** Collapsible live events feed; auto-scrolls to the newest entry. */
export function EventsFeed({
  events,
  defaultOpen = true,
  live = false,
}: {
  events: RunEvent[];
  defaultOpen?: boolean;
  live?: boolean;
}) {
  const [open, setOpen] = React.useState(defaultOpen);
  const bottomRef = React.useRef<HTMLDivElement | null>(null);

  React.useEffect(() => {
    if (open) {
      bottomRef.current?.scrollIntoView({ block: "nearest" });
    }
  }, [events.length, open]);

  return (
    <div className="rounded-xl border border-border bg-card">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        className="flex w-full items-center justify-between gap-3 px-5 py-4 text-left"
      >
        <span className="text-sm font-semibold tracking-tight">
          Events
          {live ? (
            <span className="ml-2 inline-flex items-center gap-1 rounded-full bg-emerald-500/15 px-2 py-0.5 text-[10px] font-medium text-emerald-400">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-400" />
              LIVE
            </span>
          ) : null}
          <span className="ml-2 font-mono text-xs font-normal text-muted-foreground">
            {events.length}
          </span>
        </span>
        <span className="text-xs text-muted-foreground">
          {open ? "hide" : "show"}
        </span>
      </button>
      {open ? (
        <div className="max-h-80 overflow-y-auto border-t border-border px-2 py-2 scrollbar-thin">
          <ol className="space-y-0.5">
            {events.map((event) => (
              <li
                key={event.seq}
                className="flex items-baseline gap-3 rounded-md px-3 py-1.5 font-mono text-xs hover:bg-muted/60"
              >
                <span className="w-8 shrink-0 text-right text-muted-foreground/60">
                  {event.seq}
                </span>
                {event.stage ? (
                  <span
                    className={cn(
                      "shrink-0 rounded bg-muted px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-muted-foreground",
                    )}
                  >
                    {event.stage}
                  </span>
                ) : null}
                <StatusBadge status={event.status} className="shrink-0" />
                <span className="min-w-0 flex-1 break-words text-foreground/90">
                  {event.message}
                </span>
              </li>
            ))}
          </ol>
          {events.length === 0 ? (
            <p className="px-3 py-2 text-xs text-muted-foreground">
              Waiting for events…
            </p>
          ) : null}
          <div ref={bottomRef} />
        </div>
      ) : null}
    </div>
  );
}
