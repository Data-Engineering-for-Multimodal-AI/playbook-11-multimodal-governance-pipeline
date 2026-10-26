# Autonomous Medical Cart Multimodal Pipeline

**Chapter 11 playbook** from *Data Engineering for Multimodal AI* (O'Reilly, 2026). Page numbers to be confirmed.
Book: https://oreil.ly/data-engineering-multimodal

> Want the code exactly as printed? Use the `first-edition` tag. This branch is the 2026 maintenance update; see [Differences from the printed book](#differences-from-the-printed-book).

## What you'll build

A governed data pipeline for Eighteen Labs' autonomous medical cart (a fictional company). The cart takes a prescription, fetches the medication, drives to the patient and hands it over. Four kinds of data feed it, and every step is checked, logged and audited:

| Data | What the cart does with it |
|---|---|
| 55,500 patient records (CSV) | Redacts them, encrypts them, and checks that nothing identifying is left |
| 6 medication labels (barcode images) | Decodes them, screens them for personal data, and verifies each one against the pharmacy formulary |
| Camera video | Detects people in its path and decides to yield or proceed |
| Body-worn sensor logs (MHEALTH) | Tells "still" from "moving", so a handover happens only when the cart is still |

On top of that, it builds:

- **Security:**
  - Keyed pseudonyms for patients, doctors and hospitals; age bands; years instead of dates.
  - A check that fails if any of the 111,073 names survives, and a k-anonymity measurement.
  - Encryption with keys read from environment variables.
  - Role-based access in which every decision, granted or denied, is logged.
- **Governance:**
  - An append-only lineage ledger whose hashes cover every field, and a demo of it catching tampering.
  - Provenance per modality.
  - A scan of everything the run wrote, looking for plaintext names.
- **Responsible AI:**
  - Whether automatic verification works equally well for every patient group.
  - Explanations for each failure.
  - Stress tests: blurred, covered and rotated labels; blocked, blurred and dark camera views; noisy and lossy sensors.
- **One verdict:** the console, both reports and the exit code all come from the same list of checks.

## Quick start

You need Python 3.12 or newer and about 250 MB of disk space for the environment. The sample data (90 MB) is in the repository; nothing is downloaded.

```bash
# Clone the repository
git clone https://github.com/Data-Engineering-for-Multimodal-AI/playbook-11-multimodal-governance-pipeline.git
cd playbook-11-multimodal-governance-pipeline

# Create and activate a virtual environment, then install dependencies
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt

# Verify installation
python medical_cart_pipeline.py --help
```

With [uv](https://docs.astral.sh/uv/): `uv sync`, then prefix commands with `uv run`. The Makefile has shortcuts: `make run`, `make pipeline`, `make journey`, `make verify`, `make tamper-demo`, `make smoke`.

### 1. Set the keys (optional, recommended)

```bash
cp .env.example .env    # then fill in both values
set -a; . ./.env; set +a
```

| Variable | Used for |
|---|---|
| `MEDICAL_CART_ENCRYPTION_KEY` | The passphrase for `staged_data/secure/*.enc` (PBKDF2-HMAC-SHA256, 600,000 iterations, a random salt per file, Fernet) |
| `MEDICAL_CART_PSEUDONYM_KEY` | The secret behind the pseudonyms (HMAC-SHA256), so nobody can rebuild them from a list of names |

Without them the run still works. It uses one-time keys, and the encryption check warns that the files can't be decrypted afterwards.

### 2. Run the pipeline and the cart journey

```bash
python medical_cart_pipeline.py
```

This takes about 12 seconds on a laptop CPU, or about 45 seconds the first time after installing, while Python compiles and caches the libraries. You'll see one line per check (see [Expected output](#expected-output)), the journey, and where the reports went.

| Command | What it runs |
|---|---|
| `python medical_cart_pipeline.py --mode pipeline` | Only the data pipeline and its checks |
| `python medical_cart_pipeline.py --mode journey` | The pipeline, then only the journey summary |
| `python medical_cart_pipeline.py --user-role admin --verbose` | As another role (`admin`, `medical_staff` (default), `cart_operator`, `auditor`), with debug logging |

**Exit codes:** 0 when every check passes or only warns, 1 when one fails.

| Role | Records (redact and encrypt) | Labels, camera, sensors | Governance audit |
|---|---|---|---|
| `admin` | read, write | read, write | yes |
| `medical_staff` | read, write | read | yes |
| `cart_operator` | none | read, write | no |
| `auditor` | none | read | yes |

As `cart_operator`, the redaction is denied and logged. Nothing downstream ever sees unredacted records, so prescription matching and the fairness check report "not run".

### 3. Read the reports

| File | What's in it |
|---|---|
| `reports/audit_report_<run>.md` | Every check with its reason, plus tables for the labels, robustness, fairness and explanations |
| `reports/audit_report_<run>.json` | The same data, machine-readable |
| `reports/cart_journey_<run>.json` | The five journey stages and the verdict |
| `staged_data/secure/healthcare_redacted.csv.enc` | The redacted records. They are only ever written encrypted |
| `staged_data/navigation_frames/*.png` | 4 keyframes, pixelated, with the detections and the path zone drawn |
| `governance.db`, `access_log.json` | The lineage ledger and the access log, kept across runs |

To read the encrypted records, set the same `MEDICAL_CART_ENCRYPTION_KEY` and run:

```bash
python security_module.py decrypt staged_data/secure/healthcare_redacted.csv.enc | head -3
```

### 4. Verify the ledger, and watch it catch tampering

```bash
python verify_lineage.py                # recompute every hash; exit 1 if the chain is broken
python verify_lineage.py --tamper-demo  # works on a temporary copy
```

```
1. Ledger as recorded: VALID (11 events recomputed)

   Edited the metadata of event 5 (phi_redaction/healthcare_csv)
2. After editing: BROKEN at event 5 - content changed after it was recorded

   Recomputed event 5's hash to match the edit
3. After re-hashing it: BROKEN at event 6 - link to the previous event doesn't match

   Deleted event 5 from a fresh copy
4. After deleting: BROKEN at event 6 - sequence gap: expected event 5, found 6
```

This output is from the first run on an empty ledger. Someone who rewrites every later event as well can hide an edit. To catch that, keep a copy of the latest hash somewhere else, for example a signed log.

## Tested on

| Date | OS | Python | Result |
|---|---|---|---|
| 2026-10-26 | macOS 26.5.1 (Apple M3) | 3.12.15 and 3.13.16 | `make smoke` (8 tests); fresh clone with `pip install -r requirements.txt` (10 s), first run 46 s, later runs 11-12 s; output below |
| 2026-10-26 | Ubuntu (GitHub Actions) | 3.12, 3.13 | `make smoke`, full run, lineage demo, and every printed command after `pip install -r requirements.txt` |

The versions are pinned in `uv.lock` and `requirements.txt`: pandas 3.1, NumPy 2.5, OpenCV 5.0 (contrib), zxing-cpp 3.1 and cryptography 50.

## Differences from the printed book

The commands printed in the book still work: `pip install -r requirements.txt`, `python medical_cart_pipeline.py` and all its options. The module and class names are unchanged. What changed is that the checks are now real. In the printed version, most of them reported success without doing the work:

| Area | Printed version | Now |
|---|---|---|
| Install | `requirements.txt` listed a package that doesn't exist (`sqlite3-to-pandas`) and standard-library modules, and pinned pandas 2.0.3 (no wheel for Python 3.12) | Pinned and locked; Python 3.12 and 3.13 |
| Running | The default workspace was an absolute path on the author's machine | The repository folder |
| PHI redaction | A `[A-Z][a-z]+` pattern missed 99.9% of the names (they have mixed case); doctors and dates were kept; the pseudonyms were unsalted MD5; the raw CSV was copied in plaintext to `staged_data/` | Keyed pseudonyms; years and length of stay instead of dates; a verification step; nothing unredacted written |
| Encryption | Password and salt were hard-coded, and a plaintext copy stayed next to each encrypted file | Keys from environment variables, a random salt per file, a decryption check, no plaintext copies |
| Lineage | The hash left out the metadata; validation never recomputed it; events were ordered by timestamp text | Every field hashed, ordered by sequence, recomputed on each audit; tamper demo |
| Barcodes | The scans were hard-coded strings with made-up confidences; the images were never read | Decoded with zxing-cpp, screened for personal data, checked against `sample-data/formulary.csv` and GS1 check digits |
| Telemetry | The MHEALTH logs stayed inside the zip, so 0 subjects were analysed and the stage reported success | Read from the zip: 10 subjects, 1.2 million samples |
| Video | "Corridor width" from vertical lines in a video that shows an outdoor plaza; crashed on OpenCV 5 | People in the cart's path, with a HOG person detector (OpenCV contrib) |
| Bias | Each group's made-up confidence minus 0.7, so identical outcomes still scored "high bias" | The gap in real outcomes between groups, and the four-fifths ratio |
| Access log | Every entry said success; a denied request raised an error before it was logged | Every decision logged, granted or denied |
| Verdict | "Pipeline execution completed successfully!" with exit code 0 even when the pipeline reported FAILED; the report's summary and final status disagreed | One verdict for the console, the reports and the exit code |
| Modes | `both` ran the whole pipeline twice | Once |

Some parts of the printed version were removed:

- **Navigation "route bias".** It measured the frame width and the edge density, which aren't route choices.
- **The explainability score.** There is now a written reason for each failure instead.
- **The README's API reference.** It described functions that don't exist.

`sample-data/formulary.csv` and `verify_lineage.py` are new.

## Data and licenses

| File | Source | License |
|---|---|---|
| `sample-data/healthcare_dataset.csv` | [Healthcare Dataset](https://www.kaggle.com/datasets/prasad22/healthcare-dataset), Kaggle (prasad22): synthetic records; the names are generated, not real patients | CC0 1.0 |
| `sample-data/mhealth+dataset.zip`, `sample-data/MHEALTHDATASET/README.txt` | [MHEALTH](https://archive.ics.uci.edu/dataset/319/mhealth+dataset), UCI Machine Learning Repository (Banos et al., 2014, doi:10.24432/C5TW22) | CC BY 4.0 |
| `sample-data/bar-codes/*.png` | Test images from the [ZXing](https://github.com/zxing/zxing) project | Apache-2.0 |
| `sample-data/samples_data_vtest.avi` | `vtest.avi` from OpenCV's [`samples/data`](https://github.com/opencv/opencv/tree/4.x/samples/data). Its resolution and length (768×576, 795 frames) match the PETS 2009 benchmark sequence S2.L1, filmed at the University of Reading. OpenCV doesn't state its source; we didn't find the PETS terms of use online | Distributed with OpenCV (Apache-2.0); PETS 2009 terms unconfirmed |
| `sample-data/formulary.csv` | Written for this playbook (2026): a fictional formulary that assigns the four product-style test barcodes to four of the five medications | MIT, like the code |

Two of the ZXing test images carry personal data, and they are kept as committed:

- **`datamatrix-1.png`:** a name with an SSN-format number and dates.
- **`qrcode-1.png`:** a contact card with a name, phone number and email.

The pipeline treats this as a finding. It quarantines both labels, never stores or prints their content, and stages only their format.

## Expected output

From `python medical_cart_pipeline.py` on 2026-10-26, macOS 26.5.1, Python 3.13.16, with no keys set. The log lines are left out; the run ID and paths differ on each run.

```
Pipeline Status: PASS WITH WARNINGS
  [PASS] Ingestion: All four modalities read - 4/4 modalities
  [PASS] Security: Access control - 8 decisions logged, 3 denied (medical_staff write barcode_data; medical_staff write navigation_data; medical_staff write telemetry_data)
  [PASS] Security: PHI redaction verified - 111073 patient, doctor and hospital names looked for, 0 found; no contact details or exact dates
  [WARN] Security: Re-identification risk (k-anonymity, k >= 5) - k=1 over Age, Gender, Admission Year, Blood Type; 111 records in groups smaller than 5
  [WARN] Security: Label payloads screened for personal data - 2 of 6 labels carry personal data and were quarantined
  [WARN] Security: Encryption at rest - 1 file(s) encrypted; MEDICAL_CART_ENCRYPTION_KEY not set: one-time key, the files cannot be decrypted after this run
  [PASS] Governance: Lineage hash chain - 11 events recomputed
  [PASS] Governance: Provenance complete for this run - every modality went through its stages
  [PASS] Governance: No plaintext names on disk - 7 files scanned
  [WARN] Inference: Prescriptions verifiable by label - 43928 of 54966 (79.9%); 4 of 5 medications have a verified label
  [PASS] Inference: Motion monitor on held-out subjects - balanced accuracy 0.991 on subjects 6, 7, 8, 9, 10
  [PASS] Responsible AI: Fairness across patient groups - largest gap in auto-verification between groups 1.2%, lowest ratio 0.985
  [PASS] Responsible AI: Fairness across people (motion monitor) - accuracy gap between subjects 0.019
  [WARN] Responsible AI: Navigation robustness - same decision in 85% of degraded views; 11 missed yields
  [WARN] Responsible AI: Label robustness - labels decoded in 53% of degraded scans
  [WARN] Responsible AI: Sensor robustness - worst balanced accuracy with a degraded sensor 0.500

Journey Status: DELIVERED_WITH_WARNINGS
  Prescription Receipt: SUCCESS
  Medication Retrieval: WARNING
  Navigation To Patient: WARNING
  Delivery Verification: SUCCESS
  Return Journey: WARNING

Pipeline finished: PASS WITH WARNINGS (9 passed, 7 warnings, 0 failed)
```

With both keys set, the encryption check passes (10 passed, 6 warnings). Each warning is a real finding, and the Markdown report explains it:

- **k = 1.**
  - Even without names, 111 records sit in groups of fewer than 5 records with the same age band, gender, admission year and blood type.
  - The records are encrypted and internal; before releasing any of them, coarsen these fields.
- **79.9% verifiable.**
  - Lipitor has no label in the formulary, so its 11,038 prescriptions need a manual check.
  - The 534 exact duplicate rows in the CSV are dropped before counting.
- **Fairness.**
  - Lipitor prescriptions are spread evenly across patient groups, so the gap stays at 1.2%.
  - If one group received most of the Lipitor, this check would flag it.
- **Navigation.**
  - Of the 17 sampled frames with a person in the path, the cart misses the person in 7 when the centre of the view is blocked, and in 2 each with motion blur and in low light.
  - HOG also misses some people in clear views. That is why the keyframes are pixelated whole: blurring only the detected people would leave the others recognizable.
- **Labels.**
  - Every label decodes slightly blurred (σ=1), rotated 10° or 90°, noisy (σ=15) or in low light.
  - Covering 5% of the code stops all six.
  - The 2-D codes survive more conditions (69%) than the 1-D codes (38 to 46%).
- **Sensors.**
  - The motion monitor uses one threshold: a 2-second window counts as still when the chest acceleration varies less than 0.2355 m/s².
  - That threshold is so low that added noise of σ=0.2 m/s² brings it down to 0.672 balanced accuracy, and σ=0.5 to chance (0.500).
  - Losing 20% or 50% of the samples doesn't hurt (0.991, 0.993).
  - Robustness checks are stress tests on deliberately damaged inputs. They can warn but never fail the run.

## License

MIT; see [LICENSE](LICENSE). The datasets keep their own licenses (above).

This is a teaching prototype, not a medical device. Real deployments need a privacy and security review and regulatory approval.
