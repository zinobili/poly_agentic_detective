# Reviews

Agents return a summary of at most 250 words; the full report is a file.

- Step reports live with their study: `docs/studies/<study>/reviews/step<N>_build_r<K>.md`
  (builder) and `step<N>_r<K>.md` (validator).
- Pre-push code reviews live with the study they cover:
  `docs/studies/<study>/reviews/push_<date>_crusader.md`.
- This folder holds only the pre-push reviews that span several studies or touch only shared
  code (`core/`, the harness, the repo layout).
