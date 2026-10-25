import { TaskSubmission } from "@/components/repository-input/task-submission";

export default function HomePage() {
  return (
    <div className="space-y-10">
      <section className="max-w-2xl space-y-3">
        <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">
          Ship evidence-first contributions
        </h1>
        <p className="text-sm leading-relaxed text-muted-foreground">
          RepoMate pins a repository snapshot, gathers cited evidence, drafts a
          contribution plan, generates a patch, and verifies it — every claim
          traceable to a file and line range.
        </p>
      </section>

      <section aria-label="Start a run">
        <TaskSubmission />
      </section>

      <section aria-label="How it works" className="max-w-2xl">
        <ol className="grid gap-3 sm:grid-cols-2">
          {[
            ["1 · Snapshot", "Pin the default branch at a commit, map languages and entry points."],
            ["2 · Evidence", "Collect issue, doc, source and test excerpts with rationale."],
            ["3 · Plan", "Summarize the task, planned changes and acceptance criteria."],
            ["4 · Patch", "Generate a unified diff and run verification checks."],
          ].map(([title, body]) => (
            <li
              key={title}
              className="rounded-xl border border-border bg-card p-4"
            >
              <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                {title}
              </p>
              <p className="mt-1.5 text-sm leading-relaxed text-foreground/85">
                {body}
              </p>
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}
