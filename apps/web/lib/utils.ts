import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/** Merge Tailwind class names, last-wins with conflict resolution. */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

/** Human-friendly timestamp, e.g. "Oct 25, 2026, 14:03:22". */
export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

/** Truncate long identifiers, keeping the head. */
export function truncate(text: string, max = 64): string {
  if (text.length <= max) return text;
  return `${text.slice(0, max - 1)}…`;
}

/** Human-friendly execution duration. */
export function formatDuration(ms: number | null | undefined): string {
  if (typeof ms !== "number") return "—";
  if (ms < 1000) return `${ms} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
}

/** Human-friendly byte count. */
export function formatBytes(bytes: number | null | undefined): string {
  if (typeof bytes !== "number") return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
