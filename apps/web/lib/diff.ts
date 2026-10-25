/**
 * Single-pass unified-diff parser (O(n) in patch lines).
 *
 * Produces one DiffFile per `diff --git a/... b/...` header (or one implicit
 * file for bare patches), with typed lines and tracked old/new line numbers
 * for side-by-side gutter rendering.
 */

export type DiffLineType = "context" | "add" | "remove" | "hunk" | "file";

export interface DiffLine {
  type: DiffLineType;
  text: string;
  /** Line number in the pre-image (context/remove lines). */
  oldNo?: number;
  /** Line number in the post-image (context/add lines). */
  newNo?: number;
}

export interface DiffFile {
  /** [oldPath, newPath] parsed from the header, or null for bare patches. */
  paths: [string, string] | null;
  lines: DiffLine[];
}

const GIT_HEADER = "diff --git ";
const HUNK_RE = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/;

function parseGitPaths(header: string): [string, string] | null {
  const body = header.slice(GIT_HEADER.length);
  const split = body.indexOf(" b/");
  if (split === -1) return null;
  const oldPath = body.slice(0, split).replace(/^a\//, "");
  const newPath = body.slice(split + 3).replace(/^b\//, "");
  return [oldPath, newPath];
}

export function parseUnifiedDiff(patch: string): DiffFile[] {
  const files: DiffFile[] = [];
  let current: DiffFile | null = null;
  let oldNo = 0;
  let newNo = 0;
  let inHunk = false;

  const ensureFile = (): DiffFile => {
    if (current === null) {
      current = { paths: null, lines: [] };
      files.push(current);
    }
    return current;
  };

  for (const raw of patch.split("\n")) {
    const line = raw.endsWith("\r") ? raw.slice(0, -1) : raw;

    if (line.startsWith(GIT_HEADER)) {
      current = { paths: parseGitPaths(line), lines: [] };
      files.push(current);
      current.lines.push({ type: "file", text: line });
      inHunk = false;
      continue;
    }

    const file = ensureFile();

    if (line.startsWith("\\") || line === "") {
      // "\ No newline at end of file" markers and trailing blank lines.
      file.lines.push({ type: "file", text: line });
      continue;
    }

    if (line.startsWith("@@")) {
      const match = HUNK_RE.exec(line);
      if (match) {
        oldNo = Number.parseInt(match[1], 10);
        newNo = Number.parseInt(match[2], 10);
      }
      inHunk = true;
      file.lines.push({ type: "hunk", text: line });
      continue;
    }

    if (!inHunk) {
      // Pre-hunk metadata: index lines, ---/+++ headers, mode changes.
      file.lines.push({ type: "file", text: line });
      continue;
    }

    if (line.startsWith("+")) {
      file.lines.push({ type: "add", text: line, newNo });
      newNo += 1;
    } else if (line.startsWith("-")) {
      file.lines.push({ type: "remove", text: line, oldNo });
      oldNo += 1;
    } else {
      const text = line.startsWith(" ") ? line : ` ${line}`;
      file.lines.push({ type: "context", text, oldNo, newNo });
      oldNo += 1;
      newNo += 1;
    }
  }

  return files;
}
