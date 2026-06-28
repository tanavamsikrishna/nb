- Can purity linter be extended to flag free variable modifications?
- [ ] Add support for experiment tracking
  1. A new full-run creates a new "run"
  2. Running a cell creates a nested run
  3. **Things to log**:
     1. All display records
     2. All relevant code (Whole notebook for a full run, code of any cells run during nested run)
     3. Expose a function to log binary objects.
