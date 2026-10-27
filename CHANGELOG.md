# Changelog

## 2026.10.1 (2026-10-27)

### Changed
- README, after checking against the book (Early Release, pages 433–445): page numbers; the commands
  the book prints (page 443); the differences table's left column is the first edition.

## 2026.10 (2026-10-26)

Maintenance update. The code as printed in the book is tagged `first-edition`. The printed commands and the module and class names are unchanged.

### Fixed
- `pip install -r requirements.txt` failed on every Python version:
  - `sqlite3-to-pandas` doesn't exist on PyPI.
  - The file listed standard-library modules.
  - pandas 2.0.3 has no wheel for 3.12.
- The default `--workspace` was an absolute path on the author's machine; it is now the repository folder.
- OpenCV 5 crashed the navigation stage, and the run still printed "completed successfully" with exit code 0.
- PHI redaction:
  - It missed 99.9% of the patient names (mixed case) and all doctors and dates.
  - The pseudonyms were unsalted MD5.
  - The raw CSV was copied in plaintext to `staged_data/`.
- Encryption used a hard-coded password and salt, ignored `MEDICAL_CART_ENCRYPTION_KEY`, and left a plaintext copy next to the encrypted file.
- Lineage validation never recomputed hashes, and the hash left out the metadata, so edits went unnoticed.
- The barcode "scans" were hard-coded strings with made-up confidences.
- The MHEALTH logs were never read (0 subjects analysed, reported as success).
- "Bias" was a made-up confidence minus 0.7.
- The access log recorded only successes.
- The report's summary and final status contradicted each other.
- `--mode both` ran the pipeline twice.

### Changed
- **Security:**
  - Keyed HMAC pseudonyms for patients, doctors and hospitals (`MEDICAL_CART_PSEUDONYM_KEY`).
  - Admission year and length of stay instead of dates; age bands.
  - A redaction check over 111,073 names, and a k-anonymity measurement.
  - Encryption from `MEDICAL_CART_ENCRYPTION_KEY`: PBKDF2 with a random salt per file, checked by decrypting.
  - Records are written only redacted and encrypted.
  - Every access decision is logged, and denials skip a stage instead of crashing.
- **Labels:**
  - Decoded with zxing-cpp and screened for personal data: 2 of the 6 committed images carry some and are quarantined.
  - Checked against `sample-data/formulary.csv` (new, fictional) and GS1 check digits.
  - Stress-tested under 13 conditions.
- **Camera:**
  - People in the cart's path (HOG person detector) and a yield or proceed decision.
  - Tested with the view blocked, blurred or dark.
  - The keyframes are staged pixelated.
- **Telemetry:**
  - MHEALTH read from the zip (10 subjects).
  - A still/moving monitor fitted on subjects 1-5 and scored on 6-10 against the activity labels.
  - Tested with noise and lost samples.
- **Responsible AI:**
  - Automatic-verification rates per age band, gender, condition and insurer (parity gap and four-fifths ratio).
  - Monitor accuracy per person.
  - A written reason for each failure.
- **One verdict:**
  - Every check with its reason, shared by the console, both reports and the exit code (1 only when a check fails).
  - Robustness stress tests can warn but not fail.

### Added
- `verify_lineage.py` (`--tamper-demo` shows an edit, a re-hash and a deletion being caught).
- `python security_module.py decrypt FILE.enc`.
- `.env.example`.
- `pyproject.toml` and `uv.lock`; `requirements.txt` exported from the lock (Python ≥ 3.12).
- `tests/test_smoke.py` (8 tests), `make smoke`.
- CI on Python 3.12 and 3.13, including every printed command after `pip install -r requirements.txt`.

### Removed
- Navigation "route bias" (it measured frame width and edge density).
- The explainability score.
- The README's API reference, which described functions that don't exist.
