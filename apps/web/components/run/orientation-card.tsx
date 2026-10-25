"use client";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import type { Orientation } from "@/lib/types";

export function OrientationCard({ orientation }: { orientation: Orientation }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Repository orientation</CardTitle>
        <CardDescription>
          Snapshot-derived map for newcomers — every entry traceable to the
          pinned commit{orientation.generated_by ? ` (${orientation.generated_by})` : ""}.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="text-sm leading-relaxed text-foreground">
          {orientation.summary}
        </p>

        {orientation.key_paths.length > 0 ? (
          <div>
            <p className="mb-2 text-xs font-medium text-muted-foreground">
              Key paths
            </p>
            <ul className="space-y-1.5">
              {orientation.key_paths.map((entry) => (
                <li
                  key={entry.path}
                  className="flex flex-wrap items-baseline gap-x-2 text-sm"
                >
                  <code className="font-mono text-xs text-foreground">
                    {entry.path}
                  </code>
                  <span className="text-xs text-muted-foreground">
                    {entry.role}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        {orientation.entry_points.length > 0 ? (
          <div>
            <p className="mb-2 text-xs font-medium text-muted-foreground">
              Entry points
            </p>
            <ul className="space-y-1.5">
              {orientation.entry_points.map((entry) => (
                <li
                  key={entry.path}
                  className="flex flex-wrap items-baseline gap-x-2 text-sm"
                >
                  <code className="font-mono text-xs text-foreground">
                    {entry.path}
                  </code>
                  <span className="text-xs text-muted-foreground">
                    {entry.role}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}
