/**
 * Types mirroring the RepoMate FastAPI JSON payloads (snake_case, as
 * serialized by the backend). Keep field-for-field compatible.
 */

export type RunStatus =
  | "PENDING"
  | "RUNNING"
  | "COMPLETED"
  | "NEED_MORE_INFO"
  | "FAILED"
  | "CANCELLED";

export type TaskSource = "GITHUB_ISSUE" | "REPO_TASK";

export interface RunError {
  code: string;
  message: string;
  detail?: string;
}

export interface RunEvent {
  seq: number;
  stage?: string | null;
  status: "STARTED" | "COMPLETED" | "FAILED" | "INFO";
  message: string;
  at: string;
}

export interface EntryPoint {
  path: string;
  kind: string;
  detail: string;
}

export interface Snapshot {
  owner: string;
  name: string;
  url: string;
  default_branch: string;
  commit_sha: string;
  license: {
    status: "RECOGNIZED" | "UNKNOWN" | "ABSENT";
    spdx_id?: string | null;
    file_path?: string | null;
    note: string;
  };
  languages: Record<string, number>;
  file_count: number;
  readme_path?: string | null;
  contributing_path?: string | null;
  entry_points: EntryPoint[];
  pinned_at: string;
}

export type EvidenceKind = "ISSUE" | "DOC" | "SOURCE" | "TEST" | "METADATA";

export interface Evidence {
  id: string;
  kind: EvidenceKind;
  path: string;
  start_line?: number | null;
  end_line?: number | null;
  snippet: string;
  rationale: string;
}

export interface PlannedChange {
  path: string;
  change_type: "MODIFY" | "CREATE";
  rationale: string;
}

export interface Plan {
  task_type: string;
  summary: string;
  planned_changes: PlannedChange[];
  acceptance_criteria: string[];
  evidence_ids: string[];
  limitations: string[];
  need_more_info: boolean;
  questions: string[];
  planned_by: string;
}

export interface Artifact {
  kind: string;
  patch: string;
  affected_paths: string[];
  based_on_commit: string;
  generated_by: string;
}

export interface VerificationCheck {
  name: string;
  command?: string | null;
  status: "PASSED" | "FAILED" | "NOT_RUN";
  exit_code?: number | null;
  output_tail: string;
  reason: string;
}

export interface Receipt {
  checks: VerificationCheck[];
  overall: "PASSED" | "FAILED" | "NOT_RUN";
  environment: string;
  limitations: string[];
  created_at: string;
}

export interface GitHubIssue {
  number: number;
  title: string;
  url: string;
  state: string;
  body?: string | null;
  labels: string[];
  author: string;
}

export interface RunRecord {
  run_id: string;
  status: RunStatus;
  input: {
    source: TaskSource;
    issue_url?: string | null;
    repo_url?: string | null;
    task?: string | null;
  };
  created_at: string;
  updated_at: string;
  snapshot?: Snapshot | null;
  issue?: GitHubIssue | null;
  evidence: Evidence[];
  plan?: Plan | null;
  artifact?: Artifact | null;
  receipt?: Receipt | null;
  events: RunEvent[];
  error?: RunError | null;
  planner: string;
  workspace_kept: boolean;
}

export interface RunCreated {
  run_id: string;
  status: RunStatus;
  links: Record<string, string>;
}
