/*
 * notebookPath.ts — display helpers for notebook file paths in the UI.
 *
 * Responsibilities:
 *   - Derive a basename from an absolute (or relative) path for header chips.
 *   - Match a landing-list query against a project-relative path
 *     (whitespace-split tokens, case-insensitive substring AND).
 *
 * Headers keep the raw basename (technical mono chip + full path on hover).
 * The index list shows the daemon-provided `rel` path and filters it here.
 */

/** Last path segment; accepts `/` and `\` separators. */
export function notebookBasename(path: string): string {
  const slash = Math.max(path.lastIndexOf("/"), path.lastIndexOf("\\"));
  return slash >= 0 ? path.slice(slash + 1) : path;
}

/**
 * True when every whitespace-separated token of `query` appears in `rel`
 * (case-insensitive). Empty / whitespace-only query matches everything.
 */
export function pathMatchesQuery(rel: string, query: string): boolean {
  const tokens = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  if (tokens.length === 0) return true;
  const hay = rel.toLowerCase();
  return tokens.every((t) => hay.includes(t));
}
