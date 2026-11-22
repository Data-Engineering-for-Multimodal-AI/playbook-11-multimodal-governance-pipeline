"""Run the governed pipeline on your own patient records: make check-data DIR=... and make load DIR=...

Expected folder layout:

    my_records/
      healthcare_dataset.csv   the records, with the sample's columns (see README, "Use your own data")
      formulary.csv            optional: barcode_format, barcode_value, medication, pack
      bar-codes/               optional: medication label images (.png); needs formulary.csv

--check-only reads every file and writes nothing. Without it, once every check passes, it builds a
workspace in own_data/<folder name>/ whose sample-data/ links to your files (and to the sample
video, sensor logs and, if you have none, labels), and runs
`python medical_cart_pipeline.py --workspace own_data/<folder name> --mode pipeline` on it.
Your records are linked, not copied, so no second plaintext copy is made.
"""

import argparse
import os
import re
import shutil
import subprocess
import sys

import cv2
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLE = os.path.join(ROOT, "sample-data")
CSV = "healthcare_dataset.csv"
# What data_ingestion.py requires, plus the columns the redaction and the checks use
REQUIRED = ["Name", "Age", "Gender", "Medical Condition", "Medication", "Doctor",
            "Date of Admission", "Discharge Date"]
HANDLED = REQUIRED + ["Hospital", "Blood Type", "Insurance Provider", "Billing Amount", "Room Number",
                      "Admission Type", "Test Results"]
# Column names that suggest identifiers the redaction step doesn't handle (it pseudonymizes
# Name, Doctor and Hospital and drops the dates; everything else is kept)
IDENTIFYING = re.compile(r"name|phone|mobile|email|e-mail|ssn|social|mrn|record number|address|street|zip|"
                         r"postcode|birth|dob|passport|licen[cs]e|ip address", re.I)
FORMULARY_COLUMNS = ["barcode_format", "barcode_value", "medication", "pack"]
MIN_RECORDS = 30   # the fairness check ignores groups smaller than this


def is_lfs_pointer(path):
    with open(path, "rb") as f:
        return f.read(100).startswith(b"version https://git-lfs")


def read_csv(path, rel, problems):
    if is_lfs_pointer(path):
        problems.append(f"{rel}: a Git LFS pointer, not the data (run git lfs pull)")
        return None
    try:
        return pd.read_csv(path, encoding="utf-8")
    except UnicodeDecodeError:
        problems.append(f"{rel}: not UTF-8 text")
    except (pd.errors.ParserError, pd.errors.EmptyDataError) as e:
        problems.append(f"{rel}: not a readable CSV ({str(e).splitlines()[0]})")
    return None


def check_records(folder, problems):
    path = os.path.join(folder, CSV)
    if not os.path.isfile(path):
        problems.append(f"{CSV}: missing")
        return None
    df = read_csv(path, CSV, problems)
    if df is None:
        return None
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        problems.append(f"{CSV}: missing column(s) {', '.join(missing)} (ingestion stops without them)")
    for col in df.columns:
        if col not in HANDLED and IDENTIFYING.search(col):
            problems.append(f"{CSV}: column {col!r} looks identifying, and the redaction step doesn't handle it "
                            f"(it would stay in the output). Remove it or add it to redact_dataframe")
    if missing:
        return df
    if len(df) < MIN_RECORDS:
        problems.append(f"{CSV}: {len(df)} records; needs at least {MIN_RECORDS} for the fairness check")
    age = pd.to_numeric(df["Age"], errors="coerce")
    bad_age = df.index[age.isna() | (age < 0) | (age > 120)]
    if len(bad_age):
        problems.append(f"{CSV}: Age: {len(bad_age)} value(s) not a number from 0 to 120, "
                        f"first {df.loc[bad_age[0], 'Age']!r} (row {bad_age[0] + 2})")
    for col in ("Date of Admission", "Discharge Date"):
        dates = pd.to_datetime(df[col], errors="coerce", format="mixed")
        bad = df.index[dates.isna()]
        if len(bad):
            problems.append(f"{CSV}: {col}: {len(bad)} value(s) that aren't dates, first "
                            f"{df.loc[bad[0], col]!r} (row {bad[0] + 2})")
    admitted = pd.to_datetime(df["Date of Admission"], errors="coerce", format="mixed")
    discharged = pd.to_datetime(df["Discharge Date"], errors="coerce", format="mixed")
    backwards = df.index[discharged < admitted]
    if len(backwards):
        problems.append(f"{CSV}: {len(backwards)} record(s) discharged before admission, first row {backwards[0] + 2}")
    for col in ("Name", "Medication"):
        empty = df.index[df[col].isna() | (df[col].astype(str).str.strip() == "")]
        if len(empty):
            problems.append(f"{CSV}: {col}: {len(empty)} empty value(s), first row {empty[0] + 2}")
    return df


def check_labels(folder, df, problems):
    """Returns the formulary folder to use (yours or the sample's)."""
    has_formulary = os.path.isfile(os.path.join(folder, "formulary.csv"))
    has_labels = os.path.isdir(os.path.join(folder, "bar-codes"))
    if has_labels and not has_formulary:
        problems.append("bar-codes/: needs a formulary.csv next to it to say which label is which medication")
    source = folder if has_formulary else SAMPLE
    formulary = read_csv(os.path.join(source, "formulary.csv"), "formulary.csv", problems) if has_formulary else \
        pd.read_csv(os.path.join(SAMPLE, "formulary.csv"), dtype=str)
    if formulary is not None:
        missing = [c for c in FORMULARY_COLUMNS if c not in formulary.columns]
        if missing:
            problems.append(f"formulary.csv: missing column(s) {', '.join(missing)}")
        elif df is not None and "Medication" in df.columns:
            known = set(formulary["medication"].astype(str))
            if not known & set(df["Medication"].dropna().astype(str)):
                problems.append(f"{CSV}: Medication: none of the medications is in "
                                f"{'your' if has_formulary else 'the sample'} formulary.csv "
                                f"({', '.join(sorted(known))}), so no prescription can be verified by its label")
    if has_labels:
        images = 0
        for name in sorted(os.listdir(os.path.join(folder, "bar-codes"))):
            path, rel = os.path.join(folder, "bar-codes", name), f"bar-codes/{name}"
            if name.startswith(".") or os.path.isdir(path):
                continue
            if not name.endswith(".png"):
                problems.append(f"{rel}: not a .png; the pipeline reads only .png labels")
            elif is_lfs_pointer(path):
                problems.append(f"{rel}: a Git LFS pointer, not the image (run git lfs pull)")
            elif cv2.imread(path) is None:
                problems.append(f"{rel}: can't open as an image")
            else:
                images += 1
        if not images and not any(p.startswith("bar-codes/") for p in problems):
            problems.append("bar-codes/: no .png label images")
    return has_formulary, has_labels


def scan(folder):
    """Check a folder. Returns (records, has formulary, has labels, problems). Writes nothing."""
    if not os.path.isdir(folder):
        return None, False, False, [f"{folder}: not a folder"]
    problems = []
    df = check_records(folder, problems)
    has_formulary, has_labels = check_labels(folder, df, problems)
    return df, has_formulary, has_labels, problems


def build_workspace(folder, has_formulary, has_labels):
    work = os.path.join(ROOT, "own_data", os.path.basename(os.path.normpath(folder)) or "records")
    if os.path.isdir(work):
        shutil.rmtree(work)          # a rerun starts with an empty ledger
    data = os.path.join(work, "sample-data")
    os.makedirs(data)
    links = {CSV: os.path.join(folder, CSV),
             "formulary.csv": os.path.join(folder if has_formulary else SAMPLE, "formulary.csv"),
             "bar-codes": os.path.join(folder if has_labels else SAMPLE, "bar-codes")}
    for name in ("samples_data_vtest.avi", "mhealth+dataset.zip", "MHEALTHDATASET"):
        links[name] = os.path.join(SAMPLE, name)
    for name, target in links.items():
        os.symlink(os.path.abspath(target), os.path.join(data, name))
    return work


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--dir", required=True, help="folder with healthcare_dataset.csv")
    parser.add_argument("--check-only", action="store_true", help="check the files and write nothing")
    parser.add_argument("--user-role", default="medical_staff")
    args = parser.parse_args()
    folder = os.path.abspath(args.dir)
    df, has_formulary, has_labels, problems = scan(folder)
    if problems:
        print(f"{len(problems)} problem(s) in {args.dir}; nothing was written:")
        for p in problems:
            print(f"  {p}")
        sys.exit(1)
    print(f"{args.dir}: {len(df)} records, {df['Medication'].nunique()} medications; labels and formulary: "
          f"{'yours' if has_labels else 'the sample'}. All checks passed.", flush=True)
    if args.check_only:
        return
    work = build_workspace(folder, has_formulary, has_labels)
    rel = os.path.relpath(work, ROOT)
    print(f"Workspace: {rel}/ (sample-data/ links to your files)\n", flush=True)
    result = subprocess.run([sys.executable, "medical_cart_pipeline.py", "--workspace", rel, "--mode", "pipeline",
                             "--user-role", args.user_role], cwd=ROOT)
    print(f"\nReports: {rel}/reports/. Verify its ledger: python verify_lineage.py --workspace {rel}")
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
