# Changelog

## 0.1.0 — 2026-09-25

- First version. `list`, `capture`, `derive`.
- Raw LanguageServer response saved unmodified with a SHA-256 manifest.
- Every step becomes a derived row, known type or not.
- Fails loudly: API error or zero steps exits 2 and writes nothing; a short
  capture is written and exits 3.
- Manifest records the package source hash and `git describe` of the tool.
