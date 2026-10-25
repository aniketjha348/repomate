"use client";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import type { TestGuidance } from "@/lib/types";

function CommandRow({ label, command }: { label: string; command: string }) {
  return (
    <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
      <span className="text-xs font-medium text-muted-foreground">{label}</span>
      <code className="rounded bg-muted px-2 py-1 font-mono text-xs text-foreground">
        {command}
      </code>
    </div>
  );
}

export function TestGuidancePanel({ guidance }: { guidance: TestGuidance }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Which tests to run</CardTitle>
        <CardDescription>
          Evidence-based pointers for this task — selection is keyword-based,
          the full suite remains the authoritative check.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {guidance.run_command ? (
          <div className="space-y-2">
            <CommandRow label="Full suite" command={guidance.run_command} />
            {guidance.focused_command ? (
              <CommandRow label="Start focused" command={guidance.focused_command} />
            ) : null}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">
            No supported test command in this environment.
          </p>
        )}

        {guidance.relevant_tests.length > 0 ? (
          <ul className="space-y-1.5">
            {guidance.relevant_tests.map((test) => (
              <li
                key={test.path}
                className="flex flex-wrap items-baseline gap-x-2 text-sm"
              >
                <code className="font-mono text-xs text-foreground">
                  {test.path}
                </code>
                <span className="text-xs text-muted-foreground">
                  {test.reason}
                </span>
              </li>
            ))}
          </ul>
        ) : null}

        {guidance.note ? (
          <p className="text-xs leading-relaxed text-muted-foreground">
            {guidance.note}
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}
