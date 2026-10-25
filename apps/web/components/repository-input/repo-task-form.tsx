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
import { Textarea } from "@/components/ui/textarea";

const REPO_URL_RE = /^https:\/\/github\.com\/[\w.-]+\/[\w.-]+\/?$/;

export function RepoTaskForm() {
  const router = useRouter();
  const [repoUrl, setRepoUrl] = React.useState("");
  const [task, setTask] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const [submitting, setSubmitting] = React.useState(false);

  function validate(): string | null {
    if (!REPO_URL_RE.test(repoUrl.trim())) {
      return "Enter a repository URL like https://github.com/owner/repo";
    }
    if (task.trim().length < 10) {
      return "Describe the task in at least 10 characters";
    }
    return null;
  }

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    const problem = validate();
    if (problem !== null) {
      setError(problem);
      return;
    }
    setError(null);
    setSubmitting(true);
    try {
      const created = await createRun({
        repo_url: repoUrl.trim(),
        task: task.trim(),
      });
      router.push(`/runs/${created.run_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start run");
      setSubmitting(false);
    }
  }

  return (
    <Card className="max-w-2xl">
      <CardHeader>
        <CardTitle>Start from a repository + task</CardTitle>
        <CardDescription>
          Point at any public GitHub repository and describe the change you
          want explored.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="space-y-4" noValidate>
          <div className="space-y-2">
            <Label htmlFor="repo-url">Repository URL</Label>
            <Input
              id="repo-url"
              placeholder="https://github.com/owner/repo"
              value={repoUrl}
              onChange={(e) => setRepoUrl(e.target.value)}
              autoComplete="off"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="task">Task</Label>
            <Textarea
              id="task"
              placeholder="e.g. Add a --json flag to the export command and document it in the README"
              value={task}
              onChange={(e) => setTask(e.target.value)}
              rows={4}
            />
          </div>
          {error ? (
            <p className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs text-red-400">
              {error}
            </p>
          ) : null}
          <Button type="submit" disabled={submitting} className="w-full sm:w-auto">
            {submitting ? "Starting run…" : "Start run"}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
