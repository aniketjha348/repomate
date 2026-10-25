import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import type { Snapshot } from "@/lib/types";
import { cn, formatDate } from "@/lib/utils";

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="truncate font-mono text-sm text-foreground" title={value}>
        {value}
      </dd>
    </div>
  );
}

function LicenseBadge({ snapshot }: { snapshot: Snapshot }) {
  const { license } = snapshot;
  const recognized = license.status === "RECOGNIZED";
  return (
    <span
      title={license.note}
      className={cn(
        "inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium",
        recognized
          ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-400"
          : "border-amber-500/30 bg-amber-500/10 text-amber-400",
      )}
    >
      license: {license.spdx_id ?? license.status.toLowerCase()}
      {!recognized ? " — " + license.note : ""}
    </span>
  );
}

export function SnapshotCard({ snapshot }: { snapshot: Snapshot }) {
  const languages = Object.entries(snapshot.languages)
    .sort(([, a], [, b]) => b - a)
    .slice(0, 8);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <a
            href={snapshot.url}
            target="_blank"
            rel="noreferrer"
            className="font-mono hover:underline"
          >
            {snapshot.owner}/{snapshot.name}
          </a>
          <span className="font-mono text-xs font-normal text-muted-foreground">
            @{snapshot.commit_sha.slice(0, 10)}
          </span>
          <LicenseBadge snapshot={snapshot} />
        </CardTitle>
        <CardDescription>
          Snapshot pinned {formatDate(snapshot.pinned_at)}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        <dl className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <Stat label="default branch" value={snapshot.default_branch} />
          <Stat label="files" value={String(snapshot.file_count)} />
          <Stat label="readme" value={snapshot.readme_path ?? "—"} />
          <Stat label="contributing" value={snapshot.contributing_path ?? "—"} />
        </dl>

        {languages.length > 0 ? (
          <div className="flex flex-wrap items-center gap-1.5">
            {languages.map(([language, share]) => (
              <Badge key={language} variant="muted">
                {language}
                <span className="text-muted-foreground/70">
                  {share.toFixed(0)}%
                </span>
              </Badge>
            ))}
          </div>
        ) : null}

        {snapshot.entry_points.length > 0 ? (
          <div>
            <p className="mb-2 text-xs font-medium text-muted-foreground">
              Entry points
            </p>
            <ul className="space-y-1.5">
              {snapshot.entry_points.map((entry) => (
                <li
                  key={`${entry.kind}:${entry.path}`}
                  className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 text-sm"
                >
                  <code className="font-mono text-xs text-foreground">
                    {entry.path}
                  </code>
                  <Badge variant="outline" className="text-[10px] uppercase">
                    {entry.kind}
                  </Badge>
                  <span className="text-xs text-muted-foreground">
                    {entry.detail}
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
