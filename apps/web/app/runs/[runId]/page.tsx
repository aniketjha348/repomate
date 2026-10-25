import type { Metadata } from "next";
import { RunWorkspace } from "@/components/run/run-workspace";

export const metadata: Metadata = {
  title: "Run",
};

export default async function RunPage({
  params,
}: {
  params: Promise<{ runId: string }>;
}) {
  const { runId } = await params;
  return <RunWorkspace runId={runId} />;
}
