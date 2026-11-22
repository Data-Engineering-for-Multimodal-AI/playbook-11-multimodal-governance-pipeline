"""Checks for the "Use your own data" adapter (scripts/own_records.py). No pipeline run, a few seconds."""

import os
import shutil
import sys

import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from own_records import scan  # noqa: E402

SAMPLE = os.path.join(ROOT, "sample-data")


@pytest.fixture(scope="module")
def records():
    return pd.read_csv(os.path.join(SAMPLE, "healthcare_dataset.csv")).head(300)


def write(folder, df):
    os.makedirs(folder, exist_ok=True)
    df.to_csv(os.path.join(folder, "healthcare_dataset.csv"), index=False)
    return str(folder)


def test_good_folder_passes_and_writes_nothing(tmp_path, records):
    folder = write(tmp_path, records)
    before = sorted(os.listdir(ROOT))
    df, has_formulary, has_labels, problems = scan(folder)
    assert problems == [] and len(df) == 300
    assert not has_formulary and not has_labels
    assert sorted(os.listdir(ROOT)) == before


def test_own_labels_and_formulary(tmp_path, records):
    folder = write(tmp_path, records)
    shutil.copytree(os.path.join(SAMPLE, "bar-codes"), os.path.join(folder, "bar-codes"))
    shutil.copy(os.path.join(SAMPLE, "formulary.csv"), folder)
    _, has_formulary, has_labels, problems = scan(folder)
    assert problems == [] and has_formulary and has_labels


@pytest.mark.parametrize("change,expected", [
    (lambda d: d.drop(columns=["Doctor"]), "missing column(s) Doctor"),
    (lambda d: d.assign(Email="a@example.com"), "column 'Email' looks identifying"),
    (lambda d: d.assign(**{"Home Address": "1 Main St"}), "column 'Home Address' looks identifying"),
    (lambda d: d.assign(Age=d["Age"].astype(object).where(d.index != 4, "forty")), "Age: 1 value(s) not a number from 0 to 120, first 'forty' (row 6)"),
    (lambda d: d.assign(Age=d["Age"].where(d.index != 4, 130)), "Age: 1 value(s)"),
    (lambda d: d.assign(**{"Date of Admission": d["Date of Admission"].where(d.index != 2, "soon")}), "Date of Admission: 1 value(s) that aren't dates"),
    (lambda d: d.assign(**{"Discharge Date": d["Discharge Date"].where(d.index != 2, "2000-01-01")}), "1 record(s) discharged before admission, first row 4"),
    (lambda d: d.assign(Medication=d["Medication"].where(d.index != 1)), "Medication: 1 empty value(s), first row 3"),
    (lambda d: d.assign(Medication="Metformin"), "none of the medications is in the sample formulary.csv"),
    (lambda d: d.head(10), "10 records; needs at least 30"),
])
def test_bad_records_are_reported(tmp_path, records, change, expected):
    folder = write(tmp_path, change(records.copy()))
    _, _, _, problems = scan(folder)
    assert any(expected in p for p in problems), problems


def test_bad_labels_are_reported(tmp_path, records):
    folder = write(tmp_path, records)
    os.makedirs(os.path.join(folder, "bar-codes"))
    shutil.copy(os.path.join(SAMPLE, "bar-codes", "ean13-1.png"), os.path.join(folder, "bar-codes", "label.jpg"))
    (tmp_path / "bar-codes" / "broken.png").write_bytes(b"not an image")
    (tmp_path / "bar-codes" / "lfs.png").write_bytes(b"version https://git-lfs.github.com/spec/v1\n")
    _, _, _, problems = scan(folder)
    assert problems == [
        "bar-codes/: needs a formulary.csv next to it to say which label is which medication",
        "bar-codes/broken.png: can't open as an image",
        "bar-codes/label.jpg: not a .png; the pipeline reads only .png labels",
        "bar-codes/lfs.png: a Git LFS pointer, not the image (run git lfs pull)",
    ]


def test_unreadable_files(tmp_path):
    assert scan(str(tmp_path))[3] == ["healthcare_dataset.csv: missing"]
    (tmp_path / "healthcare_dataset.csv").write_bytes("Name\nJos\xe9\n".encode("latin-1"))
    assert scan(str(tmp_path))[3] == ["healthcare_dataset.csv: not UTF-8 text"]
    (tmp_path / "formulary.csv").write_text("code,drug\n1,x\n")
    (tmp_path / "healthcare_dataset.csv").write_text("")
    problems = scan(str(tmp_path))[3]
    assert "not a readable CSV" in problems[0] and "formulary.csv: missing column(s)" in problems[1]
