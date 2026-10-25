import type { RunError } from "@/lib/types";

export function ErrorBanner({ error }: { error: RunError }) {
  return (
    <div
      role="alert"
      className="rounded-xl border border-red-500/30 bg-red-500/10 p-5"
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="rounded border border-red-500/40 bg-red-500/15 px-1.5 py-0.5 font-mono text-xs font-medium text-red-400">
          {error.code}
        </span>
        <p className="text-sm font-medium text-red-300">{error.message}</p>
      </div>
      {error.detail ? (
        <details className="mt-3 text-xs text-red-300/80">
          <summary className="cursor-pointer select-none hover:text-red-300">
            Detail
          </summary>
          <pre className="mt-2 overflow-x-auto whitespace-pre-wrap font-mono leading-relaxed">
            {error.detail}
          </pre>
        </details>
      ) : null}
    </div>
  );
}
