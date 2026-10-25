/*
 * notebookPath.ts — display helpers for notebook file paths in the UI.
 *
 * Responsibilities:
 *   - Derive a basename from an absolute (or relative) path for header chips.
 *   - Split a project-relative path into basename and parent folder for the
 *     index list (`foo.nb.py` then `dir/sub`).
 *   - Match a landing-list query against a project-relative path
 *     (whitespace-split tokens, case-insensitive substring AND).
 *
 * Headers keep the raw basename (technical mono chip + full path on hover).
 * The index list splits `rel` and filters the unsplit path here.
 */

function lastSlash(path: string): number {
  return Math.max(path.lastIndexOf("/"), path.lastIndexOf("\\"));
}

/** Last path segment; accepts `/` and `\` separators. */
export function notebookBasename(path: string): string {
  const slash = lastSlash(path);
  return slash >= 0 ? path.slice(slash + 1) : path;
}

/**
 * Basename and parent directory of a project-relative notebook path.
 * `"a/b/foo.nb.py"` → `{ name: "foo.nb.py", parent: "a/b" }`.
 * A root-level file has an empty parent.
 */
export function notebookRelParts(rel: string): {
  name: string;
  parent: string;
} {
  const slash = lastSlash(rel);
  if (slash < 0) return { name: rel, parent: "" };
  return { name: rel.slice(slash + 1), parent: rel.slice(0, slash) };
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
