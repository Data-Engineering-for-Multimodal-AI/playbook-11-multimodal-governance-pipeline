# Playbook 11: Make a hospital robot's pipeline traceable, secure and fair
**How to build governance, security and responsible AI into a multimodal pipeline.** Chapter 11 of [*Data Engineering for Multimodal AI*](https://oreil.ly/data-engineering-multimodal) (O'Reilly, 2026), pages 431–443.

A cart that carries medicine through a hospital handles patient data, so every step has to be traceable, secure and fair. In this repo, we explore this with Eighteen Labs' autonomous medical cart. Follow along to add audit lineage, patient-data redaction, access and region rules, and bias and robustness checks to its pipeline.

**The problem.** A pipeline that handles patient data has to prove where every record came from, who saw it, and that its decisions are fair.

**What you'll work with.** You'll record lineage in an audit log that can't be changed, remove patient data at ingestion, encrypt data in transit, keep inference in approved regions, and test for bias and robustness.

> Following the book? Its steps are in [Run it the way the book does](#run-it-the-way-the-book-does) and still work as printed. Want the code exactly as printed? Use the `first-edition` tag. This branch is the 2026 maintenance update; see [Differences from the printed book](#differences-from-the-printed-book).

## Run it

You need [uv](https://docs.astral.sh/uv/) and `make`. No Docker, no GPU, no API keys, and nothing is downloaded: the sample data is in the repository. Or open the repo in a GitHub Codespace, where uv and `make` are ready. On Windows without `make`, use a Codespace or the book's steps below.

**1. Get the code.** The clone is about 172 MB, including 90 MB of sample data.

```bash
git clone https://github.com/Data-Engineering-for-Multimodal-AI/playbook-11-multimodal-governance-pipeline.git
cd playbook-11-multimodal-governance-pipeline
```

**2. Run the pipeline and the cart journey.** Installs the locked dependencies (`uv sync`) and runs `python medical_cart_pipeline.py`: ingestion of the four modalities, redaction and encryption, the lineage ledger, inference, the fairness and robustness checks, then the five journey stages. On a Mac this took 26 s with the environment installed, while other jobs were running.

```bash
make run
```

You should see one line per check, then the journey and the verdict:

```
  [PASS] Security: PHI redaction verified - 111073 patient, doctor and hospital names looked for, 0 found; no contact details or exact dates
  [WARN] Security: Re-identification risk (k-anonymity, k >= 5) - k=1 over Age, Gender, Admission Year, Blood Type; 111 records in groups smaller than 5
  [PASS] Governance: Lineage hash chain - 11 events recomputed
  [PASS] Responsible AI: Fairness across patient groups - largest gap in auto-verification between groups 1.2%, lowest ratio 0.985
Journey Status: DELIVERED_WITH_WARNINGS
Pipeline finished: PASS WITH WARNINGS (9 passed, 7 warnings, 0 failed)
```

The 16 checks are listed and explained in [Expected output](#expected-output). The reports are in `reports/`.

**3. Read the encrypted records.** Without keys the run encrypts with a one-time key, so nobody can read the file afterwards. Set both keys (any values; `.env.example` shows how to generate real ones), run the data pipeline again (`python medical_cart_pipeline.py --mode pipeline`), and decrypt the output (`python security_module.py decrypt`):

```bash
export MEDICAL_CART_ENCRYPTION_KEY=try-it-passphrase MEDICAL_CART_PSEUDONYM_KEY=try-it-pseudonym-key
make pipeline
uv run python security_module.py decrypt staged_data/secure/healthcare_redacted.csv.enc | head -3
```

```
  [PASS] Security: Encryption at rest - 1 file(s) encrypted; each one decrypts back to its content
Patient ID,Age,Gender,Blood Type,Medical Condition,Clinician ID,Facility ID,Insurance Provider,Billing Amount,Room Number,Admission Type,Medication,Test Results,Admission Year,Length of Stay (days)
PATIENT_0DEFF681888A,30-49,Male,B-,ONCOLOGICAL_CONDITION,CLINICIAN_F6F70FEE2658,FACILITY_25CD1CB36ABD,Blue Cross,18856.281305978155,328,Urgent,Paracetamol,Normal,2024,2
```

Names became keyed pseudonyms, ages became bands and dates became the admission year and the length of stay. The pseudonyms depend on `MEDICAL_CART_PSEUDONYM_KEY`, so yours differ unless you use the same key. Billing amounts and room numbers are kept exactly as they were.

**4. Check the ledger, then tamper with a copy.** `python verify_lineage.py` recomputes every hash in `governance.db`; `--tamper-demo` edits, re-hashes and deletes events in a temporary copy:

```bash
make verify
make tamper-demo
```

```
Lineage ledger: VALID (22 events recomputed)
...
2. After editing: BROKEN at event 5 - content changed after it was recorded
3. After re-hashing it: BROKEN at event 6 - link to the previous event doesn't match
4. After deleting: BROKEN at event 6 - sequence gap: expected event 5, found 6
```

22 events: the ledger keeps every run, and steps 2 and 3 each added 11.

**5. Run as another role.** A cart operator may not touch patient records:

```bash
uv run python medical_cart_pipeline.py --user-role cart_operator --mode pipeline
```

```
  [PASS] Security: Access control - 8 decisions logged, 2 denied (cart_operator write healthcare_data; cart_operator audit governance)
  [WARN] Security: PHI redaction verified - healthcare records were not processed
  [WARN] Responsible AI: Fairness across patient groups - not run (no redacted records)
```

The denied requests are in `access_log.json` with the granted ones. Try `--user-role auditor` and `admin`.

**6. Clean up.**

```bash
make clean
```

This deletes `reports/`, `staged_data/`, `governance.db` (the ledger), `access_log.json` and the `own_data/` workspaces from [Use your own data](#use-your-own-data). The sample data and `.venv/` stay. Run `unset MEDICAL_CART_ENCRYPTION_KEY MEDICAL_CART_PSEUDONYM_KEY` to go back to one-time keys.

## How much time do you have?

| Time | What to do |
|---|---|
| 15 minutes | [Run it](#run-it), steps 1 to 5. On a Mac, each run of the pipeline took about 25 s. |
| 1 hour | The three [Try this](#try-this) experiments (under 20 s together on a Mac), then the Markdown report in `reports/`. |
| 1 day | [Use your own data](#use-your-own-data): run the checks on your own records, then work through [Before production](#before-production). |

## Try this

Each experiment changes one thing and measures the effect. They write nothing. The numbers below are from a Mac on 2026-11-21.

**1. How coarse must the records be before nobody stands out?** After redaction there are no names, but a record can still be singled out by what an outsider may know. k is the size of the smallest group of records with the same quasi-identifier values; the pipeline warns when k < 5. This measures k for coarser and finer versions of them.

```bash
make try-k-anonymity
```

```
quasi-identifiers               groups    k  records in groups under 5
as the pipeline redacts            445    1                        111
+ medical condition               2412    1                        220
+ insurance provider              2028    1                        136
age in 10-year bands               768    3                          7
without blood type                  60    1                          5
admission in 5-year periods        154    1                         25
both of the last two                20    7                          0
```

All 111 records in small groups belong to the 116 patients under 18, who get a band of their own. Ten-year bands, which put 13- to 19-year-olds together, leave 7 records in small groups. Dropping blood type and reporting the admission in 5-year periods reaches k = 7. An outsider who also knows the diagnosis doubles the records at risk (220).

**2. When does the fairness check notice an uneven gap?** The cart can't verify Lipitor by its label, and in the sample Lipitor is spread evenly, so every group is verified at about the same rate. This gives patients aged 70 and over more Lipitor, step by step, and reruns the same check.

```bash
make try-fairness-skew
```

```
Lipitor share in group  group verified  others verified  largest gap  lowest ratio  verdict
           20% (as is)           80.2%            79.8%         1.2%         0.985  pass
                   25%           75.2%            79.8%         4.8%         0.940  pass
                   30%           70.0%            79.8%         9.9%         0.876  pass
                   35%           64.8%            79.8%        15.1%         0.811  warning
                   40%           60.0%            79.8%        19.9%         0.751  warning
                   50%           49.7%            79.8%        30.2%         0.622  fail
```

The check passes until the oldest patients are verified 10 points less often than everyone else, and only fails at a 30-point gap. Whether a 15-point gap for one group is acceptable is a decision for people, not a default in `responsible_ai.py`. Change `GROUP` in `experiments/fairness_skew.py` to test another group.

**3. Can the motion monitor be made robust to a noisy sensor?** The monitor's threshold is fitted on clean data, and the pipeline's stress test shows it falling to chance with sensor noise. This also fits the threshold on noisy training data and scores both on the held-out subjects.

```bash
make try-sensor-noise
```

```
threshold fitted on            threshold test noise 0.0 test noise 0.1 test noise 0.2 test noise 0.5
clean data (the pipeline)         0.2355          0.991          0.992          0.672          0.500
data with noise 0.2               0.3139          0.967          0.969          0.989          0.500
data with noise 0.5               0.6139          0.940          0.940          0.941          0.958
```

Training with the noise you expect holds accuracy at that noise level and costs a few points on clean data. No single threshold works everywhere; measure the sensor you'll deploy, or fit one per sensor.

## Use your own data

Put your records in a folder, with the sample's columns:

```
my_records/
  healthcare_dataset.csv   one row per admission
  formulary.csv            optional: barcode_format, barcode_value, medication, pack
  bar-codes/               optional: medication label images, .png (needs formulary.csv)
```

The pipeline needs the columns `Name`, `Age`, `Gender`, `Medical Condition`, `Medication`, `Doctor`, `Date of Admission` and `Discharge Date`, and uses `Hospital`, `Blood Type` and `Insurance Provider` when they are there. Without your own labels, the sample's labels and formulary are used, so only Aspirin, Ibuprofen, Paracetamol and Penicillin can be verified. Check the folder first. This reads every file and writes nothing:

```bash
make check-data DIR=my_records
```

It reports every problem it finds and stops if there is any. On a test folder with deliberately bad files:

```
8 problem(s) in bad_records; nothing was written:
  healthcare_dataset.csv: column 'Email' looks identifying, and the redaction step doesn't handle it (it would stay in the output). Remove it or add it to redact_dataframe
  healthcare_dataset.csv: Age: 1 value(s) not a number from 0 to 120, first 'forty' (row 5)
  healthcare_dataset.csv: Date of Admission: 1 value(s) that aren't dates, first 'next Tuesday' (row 9)
  healthcare_dataset.csv: 1 record(s) discharged before admission, first row 11
  healthcare_dataset.csv: Medication: 1 empty value(s), first row 13
  bar-codes/: needs a formulary.csv next to it to say which label is which medication
  bar-codes/broken.png: can't open as an image
  bar-codes/label2.jpg: not a .png; the pipeline reads only .png labels
```

It also checks for missing columns, files that aren't UTF-8 or aren't CSV, Git LFS pointers, fewer than 30 records, empty names, and medications that none of the formulary's labels cover. The `Email` check matters: with that column, a run of the pipeline fails its redaction check. When everything passes, run the pipeline on your records:

```bash
make load DIR=my_records
```

This builds a workspace in `own_data/my_records/` whose `sample-data/` links to your files (not copies, so no second plaintext copy is made) and to the sample video, sensor logs and, if you have none, labels. Then it runs `python medical_cart_pipeline.py --workspace own_data/my_records --mode pipeline`, with its own ledger and reports. On 5,000 records sampled from the sample data, this took 24 s on a Mac:

```
my_records: 5000 records, 5 medications; labels and formulary: the sample. All checks passed.
Workspace: own_data/my_records/ (sample-data/ links to your files)
  [PASS] Security: PHI redaction verified - 13978 patient, doctor and hospital names looked for, 0 found; no contact details or exact dates
  [WARN] Security: Re-identification risk (k-anonymity, k >= 5) - k=1 over Age, Gender, Admission Year, Blood Type; 105 records in groups smaller than 5
  [WARN] Inference: Prescriptions verifiable by label - 3959 of 4995 (79.3%); 4 of 5 medications have a verified label
  [PASS] Responsible AI: Fairness across patient groups - largest gap in auto-verification between groups 3.4%, lowest ratio 0.958
Pipeline finished: PASS WITH WARNINGS (9 passed, 7 warnings, 0 failed)
```

With fewer records the gaps between groups grow (3.4% instead of 1.2%), because each group is smaller. `python verify_lineage.py --workspace own_data/my_records` checks that workspace's ledger. Set the two keys first if you want to decrypt the output.

## What you end up with

A pipeline you can point at your own patient records that redacts and encrypts them, records every step in a tamper-evident ledger, logs every access decision, and reports fairness and robustness with numbers, plus measurements of where its privacy and fairness checks stop protecting you.

Skills you'll practice:
- Pseudonymizing and generalizing records, and measuring re-identification risk with k-anonymity
- Encrypting data at rest with keys from the environment
- Recording lineage in a hash chain and showing that it catches tampering
- Logging access decisions by role
- Measuring fairness across groups, and seeing what a threshold lets through
- Stress-testing a model with degraded inputs, and training for them

## Before production

This playbook is a teaching prototype, not a medical device. Before you run something like it for real:

1. **Generalize the quasi-identifiers before anyone outside sees the data.** k is 1, and all 111 exposed records are patients under 18; dropping blood type and using 5-year admission periods reaches k = 7 ([Try this 1](#try-this)). Billing amounts and room numbers are still exact (step 3). *Chapter 11, "Privacy-Preserving Machine Learning" (page 423).*
2. **Redact every identifying column, not three.** `redact_dataframe` pseudonymizes `Name`, `Doctor` and `Hospital` and drops the dates; everything else passes through. A run with an `Email` column failed its redaction check, and the failure message still read "0 found; no contact details". *Chapter 11, "Protecting Data Across the Pipeline" (page 421).*
3. **Keep the keys in a secrets store, and plan for rotation.** The keys come from environment variables. Changing `MEDICAL_CART_PSEUDONYM_KEY` changes every pseudonym, so records from before and after no longer link. *Chapter 11, "Protecting Data Across the Pipeline" (page 421).*
4. **Anchor the ledger outside the database.** `verify_lineage.py` catches an edit, a re-hash and a deletion, but someone who rewrites every later event as well can hide a change. Publish the latest hash somewhere else, such as a signed log. *Chapter 11, "Lineage and Provenance Tracking" (page 416).*
5. **Set fairness limits with the people affected.** With the defaults, patients over 70 verified 10 points less often than everyone else still pass, and a 20-point gap only warns ([Try this 2](#try-this)). *Chapter 11, "Bias Detection Across Modalities" (page 426).*
6. **Train for the sensors you will have.** The motion threshold fitted on clean data scored 0.672 with noise of 0.2 m/s²; fitted on noisy data it scored 0.989 there and 0.967 on clean data ([Try this 3](#try-this)). *Chapter 11, "Adversarial Robustness" (page 429).*
7. **Don't trust a HOG detector with safety.** In degraded views the cart missed people in its path 11 times. A cart that moves near people needs a stronger detector and a stop when it can't see. *Chapter 11, "Responsible and Transparent AI" (page 426).*
8. **Enforce where inference runs.** The opening promises approved regions, but nothing in the code checks where a step runs or where data goes. Record the region with each lineage event and refuse the others. *Chapter 11, "Data Sovereignty" (page 418).*
9. **Use real identities for access control.** Roles are a table in `AccessControl`, the role is a command-line flag, and the access log is a local JSON file. *Chapter 11, "Governance Architecture" (page 418).*

## What it costs

| Where you run it | Cost |
|---|---|
| Your machine | $0. Everything runs locally: no API keys, no paid services. The environment is about 242 MB. |
| A GitHub Codespace (2 cores, 8 GB, the default size; this repo asks for no larger one) | Estimated $0.18 per hour at GitHub's list price (November 2026). A free personal account includes 120 core-hours a month, about 60 hours on this machine. In CI, `make run` took 13 s in a freshly built devcontainer. |

## How it works

Eighteen Labs is a fictional company. Its cart takes a prescription, fetches the medication, drives to the patient and hands it over. Four kinds of data feed it, and every step is checked, logged and audited:

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

## Run it the way the book does

These are the book's steps (pages 431–443), as printed apart from the fixes listed in [Differences from the printed book](#differences-from-the-printed-book). [Run it](#run-it) above runs the same steps with `make`.

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

With [uv](https://docs.astral.sh/uv/): `uv sync`, then prefix commands with `uv run`. The Makefile has shortcuts: `make run`, `make pipeline`, `make journey`, `make verify`, `make tamper-demo`, `make smoke`. `make check-data`, `make load` and `make try-*`: see [Use your own data](#use-your-own-data) and [Try this](#try-this); `uv run pytest -q tests/test_own_data.py` checks the file checks behind `make check-data`.

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
| 2026-10-26 | Ubuntu (GitHub Actions) | 3.12, 3.13 | `make smoke`, full run, lineage demo, and every printed command after `pip install -r requirements.txt`. Same results as macOS except navigation: same decision in 86% of degraded views (85% on macOS), still 11 missed yields |

The versions are pinned in `uv.lock` and `requirements.txt`: pandas 3.1, NumPy 2.5, OpenCV 5.0 (contrib), zxing-cpp 3.1 and cryptography 50.

## Differences from the printed book

The commands printed in the book still work: `python medical_cart_pipeline.py --mode pipeline --user-role medical_staff` and `--mode journey --user-role medical_staff` (page 440), and the other options. The module and class names are unchanged. What changed is that the checks are now real. In the first edition (the code at the `first-edition` tag, which the book describes), most of them reported success without doing the work:

| Area | First edition | Now |
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

Some parts of the first edition were removed:

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

From `python medical_cart_pipeline.py` on 2026-10-26, macOS 26.5.1, Python 3.13.16, with no keys set. The log lines are left out; the run ID and paths differ on each run. This is the output of this version; it may differ from the output printed in the book, and that's okay.

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
