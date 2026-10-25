import type { Metadata } from "next";
import Link from "next/link";
import { API_URL } from "@/lib/config";
import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "RepoMate",
    template: "%s · RepoMate",
  },
  description: "Evidence-first open-source contribution agent",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className="dark">
      <body className="min-h-screen bg-background font-sans text-foreground antialiased">
        <div className="flex min-h-screen flex-col">
          <header className="border-b border-border">
            <div className="mx-auto flex h-14 w-full max-w-6xl items-center justify-between gap-4 px-4">
              <Link href="/" className="flex min-w-0 items-center gap-2.5">
                <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-emerald-500/15 font-mono text-sm font-bold text-emerald-400">
                  R
                </span>
                <span className="text-sm font-semibold tracking-tight">
                  RepoMate
                </span>
                <span className="hidden truncate text-xs text-muted-foreground sm:inline">
                  evidence-first contribution agent
                </span>
              </Link>
              <a
                href={`${API_URL}/api/health`}
                target="_blank"
                rel="noreferrer"
                className="shrink-0 text-xs text-muted-foreground transition-colors hover:text-foreground"
              >
                GitHub API health ↗
              </a>
            </div>
          </header>

          <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-10">
            {children}
          </main>

          <footer className="border-t border-border">
            <div className="mx-auto flex w-full max-w-6xl flex-wrap items-center justify-between gap-2 px-4 py-4 text-xs text-muted-foreground">
              <span>RepoMate — evidence-first open-source contribution agent</span>
              <a
                href={`${API_URL}/api/health`}
                target="_blank"
                rel="noreferrer"
                className="transition-colors hover:text-foreground"
              >
                backend health
              </a>
            </div>
          </footer>
        </div>
      </body>
    </html>
  );
}
