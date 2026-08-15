// Shared marked instances for Markdown.svelte.
//
// `marked` (breaks: true) is for cell output — a single newline becomes <br>,
// matching Jupyter-style authoring.
// `markedProse` (breaks: false) is for notebook-header / hero docstrings —
// a single newline is a space so hard-wrapped Python paragraphs reflow.

import { Marked } from "marked";

export const marked = new Marked({
  breaks: true,
});

export const markedProse = new Marked({
  breaks: false,
});
