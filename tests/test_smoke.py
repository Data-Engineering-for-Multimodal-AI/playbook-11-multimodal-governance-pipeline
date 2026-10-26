"""Smoke tests: run on a laptop CPU with the committed sample data (about 30 s)."""
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import cv2
import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from cryptography.fernet import InvalidToken  # noqa: E402

from data_ingestion import DataIngestionModule  # noqa: E402
from inference_module import PrescriptionMatcher, gs1_check_digit_ok  # noqa: E402
from pipeline_architecture import (PipelineArchitecture, ProcessingStage, DataModality,  # noqa: E402
                                   new_event)
from security_module import DataEncryption, PHIRedactor, SecurityModule, SecurityRole  # noqa: E402

RECORDS = pd.DataFrame({
    'Name': ['Bobby JacksOn', 'bobby jackson', 'LesLie TErRy', 'Dr. Ann Lee MD'],
    'Age': [30, 30, 62, 91],
    'Gender': ['Male', 'Male', 'Female', 'Female'],
    'Blood Type': ['B-', 'B-', 'A+', 'O+'],
    'Medical Condition': ['Cancer', 'Cancer', 'Obesity', 'Asthma'],
    'Date of Admission': ['2024-01-31', '2024-02-01', '2019-08-20', '2022-09-22'],
    'Doctor': ['Matthew Smith', 'Matthew Smith', 'Samantha Davies', 'Tiffany Mitchell'],
    'Hospital': ['Sons and Miller', 'Sons and Miller', 'Kim Inc', 'Cook PLC'],
    'Insurance Provider': ['Blue Cross', 'Blue Cross', 'Medicare', 'Aetna'],
    'Medication': ['Paracetamol', 'Paracetamol', 'Ibuprofen', 'Lipitor'],
    'Discharge Date': ['2024-02-02', '2024-02-05', '2019-08-26', '2022-10-07'],
})


@pytest.fixture
def workspace(tmp_path):
    """An empty workspace that reads the committed sample data"""
    (tmp_path / "sample-data").symlink_to(REPO / "sample-data")
    return tmp_path


def test_redaction_leaves_no_identifiers():
    redactor = PHIRedactor(pseudonym_key=b"test-key")
    redacted, log = redactor.redact_dataframe(RECORDS)
    assert {'Name', 'Doctor', 'Hospital', 'Date of Admission', 'Discharge Date'}.isdisjoint(redacted.columns)
    # Case doesn't split a patient in two; the oldest patient falls in the open-ended band
    assert redacted['Patient ID'][0] == redacted['Patient ID'][1]
    assert redacted['Age'].tolist() == ['30-49', '30-49', '50-69', '70+']
    assert redacted['Length of Stay (days)'].tolist() == [2, 4, 6, 15]
    assert redactor.verify_redaction(RECORDS, redacted)['status'] == 'pass'
    # Pseudonyms depend on the key: without it, nobody can rebuild them from a list of names
    other, _ = PHIRedactor(pseudonym_key=b"other-key").redact_dataframe(RECORDS)
    assert set(other['Patient ID']).isdisjoint(redacted['Patient ID'])


def test_redaction_check_catches_a_leak():
    redactor = PHIRedactor(pseudonym_key=b"test-key")
    redacted, _ = redactor.redact_dataframe(RECORDS)
    redacted.loc[0, 'Test Results'] = 'leslie terry'
    redacted.loc[1, 'Insurance Provider'] = 'call 555-123-4567'
    result = redactor.verify_redaction(RECORDS, redacted)
    assert result['status'] == 'fail'
    assert result['residual_identifiers'] == 1 and 'phone' in result['residual_patterns']


def test_payload_screening():
    redactor = PHIRedactor(pseudonym_key=b"test-key")
    assert set(redactor.scan_text("Mr. John Doe\r\n123-45-6789\r\n")) == {'name', 'ssn'}
    assert {'contact_card_name', 'phone', 'email'} <= set(
        redactor.scan_text("MECARD:N:Doe,Jane;TEL:+15555550100;EMAIL:jane@example.com;;"))
    for product_code in ("9780201310054", "05012345678900", "429250", "Code 128"):
        assert redactor.scan_text(product_code) == {}


def test_encryption_roundtrip_and_wrong_key(tmp_path):
    enc = DataEncryption("correct horse")
    result = enc.encrypt_to_file(b"Patient ID,Medication\nPATIENT_1,Aspirin\n", tmp_path / "x.enc")
    assert result['roundtrip_verified']
    blob = (tmp_path / "x.enc").read_bytes()
    assert b"Aspirin" not in blob
    assert enc.encrypt_bytes(b"same") != enc.encrypt_bytes(b"same")   # random salt and IV
    with pytest.raises(InvalidToken):
        DataEncryption("wrong key").decrypt_bytes(blob)


def test_lineage_detects_tampering(workspace):
    arch = PipelineArchitecture(workspace)
    for i in range(3):
        arch.record_lineage_event(new_event(ProcessingStage.INGESTION, DataModality.HEALTHCARE_CSV,
                                            f"hash{i}", {'records': i}))
    assert arch.verify_lineage()['valid']
    with sqlite3.connect(arch.db_path) as conn:
        conn.execute("UPDATE lineage_events SET metadata = ? WHERE seq = 2", (json.dumps({'records': 99}),))
    conn.close()
    result = arch.verify_lineage()
    assert not result['valid'] and result['first_bad_seq'] == 2


def test_access_denials_are_logged(workspace):
    security = SecurityModule(PipelineArchitecture(workspace))
    result = security.secure_healthcare_data(RECORDS, SecurityRole.CART_OPERATOR)
    assert result['status'] == 'denied'
    log = security.run_access_log()
    assert log[-1]['success'] is False and log[-1]['data_type'] == 'healthcare_data'
    assert security.authorize(SecurityRole.AUDITOR, 'audit', 'governance')


def test_committed_labels_decode_and_verify(workspace):
    arch = PipelineArchitecture(workspace)
    labels = DataIngestionModule(arch).ingest_barcode_images()['data']
    assert len(labels) == 6 and all(l['decoded'] for l in labels)
    SecurityModule(arch).screen_barcode_payloads(labels, SecurityRole.MEDICAL_STAFF)
    matcher = PrescriptionMatcher(REPO / "sample-data" / "formulary.csv")
    status = {l['file']: matcher.verify_label(l)['status'] for l in labels}
    assert status == {'code128-1.png': 'verified', 'code39-1.png': 'verified', 'ean13-1.png': 'verified',
                      'itf-1.png': 'verified', 'datamatrix-1.png': 'quarantined', 'qrcode-1.png': 'quarantined'}
    assert gs1_check_digit_ok("9780201310054") and not gs1_check_digit_ok("9780201310055")


def test_pipeline_end_to_end(workspace):
    """The printed command, run in a temporary workspace"""
    env = {**os.environ, 'MEDICAL_CART_ENCRYPTION_KEY': 'smoke-test-passphrase',
           'MEDICAL_CART_PSEUDONYM_KEY': 'smoke-test-pseudonym-key'}
    run = subprocess.run([sys.executable, str(REPO / "medical_cart_pipeline.py"), "--workspace", str(workspace)],
                         capture_output=True, text=True, env=env, cwd=REPO)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "Pipeline finished: PASS" in run.stdout

    report = json.loads(next((workspace / "reports").glob("audit_report_*.json")).read_text())
    checks = {c['check']: c['status'] for c in report['executive_summary']['checks']}
    assert checks['PHI redaction verified'] == 'pass'
    assert checks['Lineage hash chain'] == 'pass'
    assert checks['No plaintext names on disk'] == 'pass'
    assert checks['Motion monitor on held-out subjects'] == 'pass'

    # No patient name anywhere in what the run wrote, reports included
    names = set(pd.read_csv(REPO / "sample-data" / "healthcare_dataset.csv", usecols=['Name'])['Name']
                .str.casefold().str.split().str.join(' '))
    for path in list((workspace / "reports").iterdir()) + list((workspace / "staged_data").rglob("*.json")):
        text = " ".join(path.read_text().casefold().split())
        assert not any(name in text for name in list(names)[:2000]), path
    assert not (workspace / "staged_data" / "healthcare_staged.csv").exists()

    frames = list((workspace / "staged_data" / "navigation_frames").glob("*.png"))
    assert frames and cv2.imread(str(frames[0])) is not None
