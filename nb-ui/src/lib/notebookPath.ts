/*
 * notebookPath.ts — display helpers for notebook file paths in the UI.
 *
 * Responsibilities:
 *   - Derive a basename from an absolute (or relative) path for header chips.
 *   - Pretty-print a notebook filename for the landing list
 *     ("abc_bcd_cxy.nb.py" → "Abc Bcd Cxy").
 *
 * Headers keep the raw basename (technical mono chip + full path on hover);
 * only the index list uses the humanized title. No daemon/API involvement —
 * pure client formatting over paths the UI already has.
 */

/** Last path segment; accepts `/` and `\` separators. */
export function notebookBasename(path: string): string {
  const slash = Math.max(path.lastIndexOf("/"), path.lastIndexOf("\\"));
  return slash >= 0 ? path.slice(slash + 1) : path;
}

/**
 * Landing-page title from a basename or full path.
 * Strips trailing `.nb.py` / `.py`, splits on `_`/`-`, title-cases each token.
 */
export function prettyNotebookTitle(nameOrPath: string): string {
  let base = notebookBasename(nameOrPath);
  base = base.replace(/\.nb\.py$/i, "").replace(/\.py$/i, "");
  return base
    .split(/[_-]+/)
    .filter(Boolean)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
    .join(" ");
}
