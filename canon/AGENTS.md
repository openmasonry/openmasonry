# canon/: local rules

- These files are governed. `eternal.toml` (Landmarks + Declaration) never changes. `degrees.toml` changes only through a passed amendment ballot that pins the new SHA-256.
- Before that ballot is opened, a pull request must archive the new table as `history/<sha256>.toml` (a byte-for-byte copy): the opening is refused without it, so old and new entries replay under the table of their time. Files in `history/` are never modified, renamed or deleted.
- After any change here, run `om arms` and `om docs` and commit the regenerated `heraldry/` and `docs/degrees/`.
