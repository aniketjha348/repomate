"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { createRun } from "@/lib/api-client";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

const ISSUE_URL_RE =
  /^https:\/\/github\.com\/[\w.-]+\/[\w.-]+\/issues\/\d+\/?$/;

export function IssueForm() {
  const router = useRouter();
  const [issueUrl, setIssueUrl] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const [submitting, setSubmitting] = React.useState(false);

  const valid = ISSUE_URL_RE.test(issueUrl.trim());

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    const url = issueUrl.trim();
    if (!ISSUE_URL_RE.test(url)) {
      setError(
        "Enter a GitHub issue URL like https://github.com/owner/repo/issues/123",
      );
      return;
    }
    setError(null);
    setSubmitting(true);
    try {
      const created = await createRun({ issue_url: url });
      router.push(`/runs/${created.run_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start run");
      setSubmitting(false);
    }
  }

  return (
    <Card className="max-w-2xl">
      <CardHeader>
        <CardTitle>Start from a GitHub issue</CardTitle>
        <CardDescription>
          RepoMate snapshots the repository, gathers evidence, plans the
          change, and proposes a patch for review. Verification runs the
          selected checks before and after the patch.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="space-y-4" noValidate>
          <div className="space-y-2">
            <Label htmlFor="issue-url">Issue URL</Label>
            <Input
              id="issue-url"
              placeholder="https://github.com/owner/repo/issues/123"
              value={issueUrl}
              onChange={(e) => setIssueUrl(e.target.value)}
              autoComplete="off"
              autoFocus
              aria-invalid={error !== null && !valid}
            />
          </div>
          {error ? (
            <p className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs text-red-400">
              {error}
            </p>
          ) : null}
          <div className="flex flex-wrap items-center gap-2">
            <Button type="submit" disabled={submitting} className="w-full sm:w-auto">
              {submitting ? "Starting run…" : "Start run"}
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
