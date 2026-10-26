/**
 * Types mirroring the RepoMate FastAPI JSON payloads (snake_case, as
 * serialized by the backend). Keep field-for-field compatible.
 */

export type RunStatus =
  | "PENDING"
  | "RUNNING"
  | "COMPLETED"
  | "NEED_MORE_INFO"
  | "PARTIAL"
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
  proposed_claims?: ProposedClaim[];
  raw_response?: string;
}

export interface ProposedClaim {
  text: string;
  evidence_ids: string[];
}

export type SupportStatus = "supported" | "hypothesis";

export interface GroundedClaim {
  text: string;
  evidence_ids: string[];
  support_status: SupportStatus;
  matched_evidence_ids: string[];
  matched_keywords: string[];
}

export interface GroundingWarning {
  code: string;
  message: string;
  evidence_id: string;
  claim_text: string;
}

export interface GroundingReport {
  claims: GroundedClaim[];
  warnings: GroundingWarning[];
  resolved_evidence_ids: string[];
  unresolved_evidence_ids: string[];
}

export interface Artifact {
  kind: string;
  patch: string;
  affected_paths: string[];
  based_on_commit: string;
  generated_by: string;
}

export interface ArtifactDocument {
  name: string;
  kind: string;
  media_type: string;
  content: string;
  generated_by: string;
}

export interface ArtifactSummary {
  name: string;
  kind: string;
  media_type: string;
  size_bytes: number;
  download_url: string;
}

export interface VerificationCheck {
  name: string;
  command?: string | null;
  status: "PASSED" | "FAILED" | "NOT_RUN";
  exit_code?: number | null;
  duration_ms?: number | null;
  output_tail: string;
  reason: string;
}

export type ComparisonOutcome =
  | "CONSISTENT_IMPROVEMENT"
  | "NO_REGRESSION_DETECTED"
  | "UNRESOLVED"
  | "POTENTIAL_REGRESSION"
  | "BASELINE_INCOMPLETE"
  | "POST_PATCH_INCOMPLETE";

export interface VerificationRun {
  phase: "baseline" | "post_patch";
  commit_sha: string;
  command?: string | null;
  status: "PASSED" | "FAILED" | "NOT_RUN";
  exit_code?: number | null;
  duration_ms?: number | null;
  output_summary: string;
  reason: string;
}

export interface VerificationComparison {
  base_commit: string;
  patch_sha256: string;
  baseline: VerificationRun;
  post_patch: VerificationRun;
  outcome: ComparisonOutcome;
  interpretation: string;
  commands_match?: boolean | null;
}

export interface SandboxPolicy {
  network_mode: string;
  backend: string;
  policy_enforced: boolean;
  egress_validation: string;
  egress_detail: string;
}

export interface Receipt {
  checks: VerificationCheck[];
  overall: "PASSED" | "FAILED" | "NOT_RUN";
  environment: string;
  limitations: string[];
  sandbox?: SandboxPolicy | null;
  base_commit?: string | null;
  patch_sha256?: string | null;
  comparison?: VerificationComparison | null;
  resolution_statement: string;
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

export interface KeyPath {
  path: string;
  role: string;
}

export interface Orientation {
  summary: string;
  key_paths: KeyPath[];
  languages: Record<string, number>;
  entry_points: KeyPath[];
  generated_by: string;
}

export interface RetrievalLimits {
  max_files: number;
  max_bytes_per_file: number;
  max_total_bytes: number;
  max_search_results: number;
  max_seconds: number;
}

export interface RetrievalLimitHit {
  limit:
    | "MAX_FILES"
    | "MAX_BYTES_PER_FILE"
    | "MAX_TOTAL_BYTES"
    | "MAX_SEARCH_RESULTS"
    | "MAX_SECONDS";
  allowed: number;
  observed: number;
  remaining_work: string;
}

export interface RetrievalReport {
  status: "COMPLETE" | "PARTIAL";
  limits: RetrievalLimits;
  files_total: number;
  files_eligible: number;
  files_examined: number;
  bytes_read: number;
  search_results: number;
  evidence_records: number;
  elapsed_ms: number;
  limit_hits: RetrievalLimitHit[];
  summary: string;
}

export interface ToolLoopLimits {
  max_tool_calls: number;
  max_total_bytes: number;
  max_seconds: number;
  max_results_per_search: number;
}

export interface ToolCallRecord {
  index: number;
  tool: "search_text" | "read_file" | "inspect_manifest" | "done";
  target: string;
  status: "OK" | "REJECTED" | "ERROR";
  detail: string;
  bytes_read: number;
  evidence_paths: string[];
}

export interface ToolLoopLimitHit {
  limit: "MAX_TOOL_CALLS" | "MAX_TOTAL_BYTES" | "MAX_SECONDS";
  allowed: number;
  observed: number;
  remaining_work: string;
}

export interface ToolLoopReport {
  status: "COMPLETE" | "PARTIAL";
  limits: ToolLoopLimits;
  model_calls: number;
  tool_calls: number;
  bytes_read: number;
  records_added: number;
  rejected_items: number;
  calls: ToolCallRecord[];
  limit_hits: ToolLoopLimitHit[];
  stop_reason: string;
  summary: string;
}

export interface ModelBudgetLimits {
  max_calls: number;
  max_tokens: number;
}

export interface ModelBudgetReport {
  limits: ModelBudgetLimits;
  calls: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  usage_source: "reported" | "estimated" | "mixed" | "none";
  exhausted: boolean;
  reason: string;
}

export interface RelevantTest {
  path: string;
  reason: string;
}

export interface TestGuidance {
  run_command?: string | null;
  focused_command?: string | null;
  relevant_tests: RelevantTest[];
  note: string;
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
  retrieval?: RetrievalReport | null;
  tool_loop?: ToolLoopReport | null;
  model_usage?: ModelBudgetReport | null;
  orientation?: Orientation | null;
  test_guidance?: TestGuidance | null;
  plan?: Plan | null;
  grounding?: GroundingReport | null;
  artifact?: Artifact | null;
  documents?: ArtifactDocument[];
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
