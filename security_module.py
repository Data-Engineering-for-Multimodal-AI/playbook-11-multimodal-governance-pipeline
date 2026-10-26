"""
Security Module for Medical Cart Pipeline

Implements:
- PHI (Protected Health Information) redaction, with a check that nothing identifying is left
- Data encryption at rest (keys from environment variables, a random salt per file)
- Role-based access control, with every decision (granted or denied) logged
- Secure data staging: patient data is written only redacted and encrypted

Keys:
    MEDICAL_CART_ENCRYPTION_KEY   passphrase for the encrypted staging files
    MEDICAL_CART_PSEUDONYM_KEY    secret for the patient and clinician pseudonyms (HMAC-SHA256)
If a key isn't set, the run uses a one-time random key and the security audit says so.

    python security_module.py decrypt staged_data/secure/healthcare_redacted.csv.enc
"""

import os
import re
import sys
import json
import hmac
import hashlib
import secrets
import base64
import uuid
import datetime
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

import cv2
import numpy as np
import pandas as pd
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from pipeline_architecture import PipelineArchitecture, ProcessingStage, DataModality, new_event

logger = logging.getLogger(__name__)

ENCRYPTION_KEY_ENV = "MEDICAL_CART_ENCRYPTION_KEY"
PSEUDONYM_KEY_ENV = "MEDICAL_CART_PSEUDONYM_KEY"


class SecurityRole:
    """User roles for access control"""
    ADMIN = "admin"
    MEDICAL_STAFF = "medical_staff"
    CART_OPERATOR = "cart_operator"
    AUDITOR = "auditor"


def normalize_identifier(value: Any) -> str:
    """'Bobby JacksOn ' and 'bobby  jackson' are the same person"""
    return " ".join(str(value).casefold().split())


def secret_from_env(name: str) -> Tuple[bytes, str]:
    """(secret, 'environment' or 'one-time')"""
    value = os.environ.get(name)
    if value:
        return value.encode(), 'environment'
    logger.warning(f"{name} is not set: using a one-time random key for this run (see .env.example)")
    return secrets.token_bytes(32), 'one-time'


class PHIRedactor:
    """Handles PHI detection and redaction"""

    def __init__(self, pseudonym_key: Optional[bytes] = None):
        self.pseudonym_key, self.key_source = ((pseudonym_key, 'given') if pseudonym_key
                                               else secret_from_env(PSEUDONYM_KEY_ENV))

        # PHI patterns for free text (barcode payloads, notes)
        self.phi_patterns = {
            'name': r'\b(?:Mr|Mrs|Ms|Miss|Dr)\.?\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*',
            'contact_card_name': r'(?:^|[;:\n])(?:N|FN):[^;\r\n]+',
            'phone': r'(?:TEL:\s*\+?[\d\s().-]{7,}|\b\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}\b)',
            'ssn': r'\b\d{3}-\d{2}-\d{4}\b',
            'email': r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b',
            'mrn': r'\bMRN\s*:?\s*\d+\b',  # Medical Record Number
            'date': r'\b(?:\d{1,2}/\d{1,2}/\d{2,4}|\d{4}-\d{2}-\d{2})\b'
        }

        # Medical condition mapping for realistic substitution
        self.medical_condition_map = {
            'Cancer': 'ONCOLOGICAL_CONDITION',
            'Diabetes': 'METABOLIC_DISORDER',
            'Obesity': 'WEIGHT_MANAGEMENT_CONDITION',
            'Hypertension': 'CARDIOVASCULAR_CONDITION',
            'Arthritis': 'MUSCULOSKELETAL_CONDITION',
            'Asthma': 'RESPIRATORY_CONDITION'
        }

        # Age bands (the oldest band is open-ended, as HIPAA Safe Harbor requires for ages over 89)
        self.age_bins = [0, 18, 30, 50, 70, 200]
        self.age_labels = ['<18', '18-29', '30-49', '50-69', '70+']

    def pseudonym(self, value: Any, prefix: str) -> str:
        """Keyed, consistent pseudonym: the same person always gets the same ID, and without the
        key nobody can recompute it from a list of names (as they could with a plain hash)."""
        digest = hmac.new(self.pseudonym_key, normalize_identifier(value).encode(), hashlib.sha256)
        return f"{prefix}_{digest.hexdigest()[:12].upper()}"

    def scan_text(self, text: str) -> Dict[str, int]:
        """Which kinds of PHI a piece of free text contains (category -> matches)"""
        found = {}
        for category, pattern in self.phi_patterns.items():
            matches = re.findall(pattern, text, flags=re.MULTILINE)
            if matches:
                found[category] = len(matches)
        return found

    def detect_phi_fields(self, df: pd.DataFrame) -> Dict[str, List[str]]:
        """Detect columns likely containing PHI"""
        phi_fields = {
            'direct_identifiers': [],
            'quasi_identifiers': [],
            'sensitive_medical': []
        }

        for col in df.columns:
            name = col.lower()
            if any(p in name for p in ['name', 'doctor', 'ssn', 'mrn', 'email', 'phone']):
                phi_fields['direct_identifiers'].append(col)
            elif any(p in name for p in ['age', 'zip', 'address', 'date', 'birth', 'hospital']):
                phi_fields['quasi_identifiers'].append(col)
            elif any(p in name for p in ['condition', 'diagnosis', 'medication', 'treatment']):
                phi_fields['sensitive_medical'].append(col)

        return phi_fields

    def redact_dataframe(self, df: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, Any]]:
        """Redact PHI from entire dataframe"""
        duplicates = int(df.duplicated().sum())
        df_redacted = df.drop_duplicates().reset_index(drop=True)
        redaction_log = {
            'phi_fields': self.detect_phi_fields(df),
            'redacted_fields': [],
            'redaction_stats': {},
            'exact_duplicates_dropped': duplicates,
            'pseudonym_key_source': self.key_source,
        }

        # Direct identifiers -> keyed pseudonyms
        for column, new_column, prefix in [('Name', 'Patient ID', 'PATIENT'),
                                           ('Doctor', 'Clinician ID', 'CLINICIAN'),
                                           ('Hospital', 'Facility ID', 'FACILITY')]:
            if column in df_redacted.columns:
                unique = df_redacted[column].dropna().unique()
                mapping = {value: self.pseudonym(value, prefix) for value in unique}
                df_redacted[column] = df_redacted[column].map(mapping)
                df_redacted = df_redacted.rename(columns={column: new_column})
                redaction_log['redacted_fields'].append(column)
                redaction_log['redaction_stats'][column] = {
                    'values_replaced': int(df_redacted[new_column].notna().sum()),
                    'distinct_values': int(len(unique)),
                    'distinct_pseudonyms': int(len(set(mapping.values())))}

        # Dates -> admission year and length of stay
        if {'Date of Admission', 'Discharge Date'} <= set(df_redacted.columns):
            admitted = pd.to_datetime(df_redacted['Date of Admission'], errors='coerce')
            discharged = pd.to_datetime(df_redacted['Discharge Date'], errors='coerce')
            df_redacted['Admission Year'] = admitted.dt.year.astype('Int64')
            df_redacted['Length of Stay (days)'] = (discharged - admitted).dt.days.astype('Int64')
            df_redacted = df_redacted.drop(columns=['Date of Admission', 'Discharge Date'])
            redaction_log['redacted_fields'] += ['Date of Admission', 'Discharge Date']

        # Medical conditions -> categories
        if 'Medical Condition' in df_redacted.columns:
            df_redacted['Medical Condition'] = (df_redacted['Medical Condition']
                                                .map(self.medical_condition_map)
                                                .fillna('OTHER_CONDITION'))
            redaction_log['redacted_fields'].append('Medical Condition')

        # Age binning for quasi-identifiers
        if 'Age' in df_redacted.columns:
            df_redacted['Age'] = pd.cut(df_redacted['Age'], bins=self.age_bins, labels=self.age_labels,
                                        right=False).astype(str)
            redaction_log['redacted_fields'].append('Age')

        redaction_log['phi_detected'] = bool(redaction_log['redacted_fields'])
        return df_redacted, redaction_log

    def verify_redaction(self, original: pd.DataFrame, redacted: pd.DataFrame) -> Dict[str, Any]:
        """Look for anything identifying that survived redaction"""
        identifiers = set()
        for column in ('Name', 'Doctor', 'Hospital'):
            if column in original.columns:
                identifiers.update(original[column].dropna().map(normalize_identifier))

        text_columns = [c for c in redacted.columns if redacted[c].dtype == object or
                        str(redacted[c].dtype) in ('string', 'str', 'category')]
        residual_identifiers = 0
        residual_patterns = {}
        for column in text_columns:
            values = redacted[column].dropna().astype(str)
            residual_identifiers += int(values.map(normalize_identifier).isin(identifiers).sum())
            for category in ('ssn', 'email', 'phone', 'date'):
                hits = int(values.str.contains(self.phi_patterns[category], regex=True).sum())
                if hits:
                    residual_patterns[category] = residual_patterns.get(category, 0) + hits

        exact_dates_left = [c for c in redacted.columns if 'date' in c.lower()]
        passed = residual_identifiers == 0 and not residual_patterns and not exact_dates_left
        return {
            'status': 'pass' if passed else 'fail',
            'identifiers_checked': len(identifiers),
            'residual_identifiers': residual_identifiers,
            'residual_patterns': residual_patterns,
            'date_columns_left': exact_dates_left,
        }

    def k_anonymity(self, redacted: pd.DataFrame,
                    quasi_identifiers=('Age', 'Gender', 'Admission Year', 'Blood Type')) -> Dict[str, Any]:
        """Smallest number of records that share the same quasi-identifier values"""
        columns = [c for c in quasi_identifiers if c in redacted.columns]
        sizes = redacted.groupby(columns, observed=True).size()
        small = sizes[sizes < 5]
        return {
            'quasi_identifiers': columns,
            'k': int(sizes.min()),
            'groups': int(len(sizes)),
            'records_in_groups_under_5': int(small.sum()),
        }


class DataEncryption:
    """Handles data encryption and decryption

    File format: b'MCART1' + 16-byte random salt + Fernet token (AES-128-CBC + HMAC-SHA256).
    The Fernet key is derived from the passphrase with PBKDF2-HMAC-SHA256 and the file's own salt.
    """

    MAGIC = b"MCART1"
    ITERATIONS = 600_000

    def __init__(self, password: Optional[str] = None):
        if password:
            self.password, self.key_source = password.encode(), 'given'
        else:
            self.password, self.key_source = secret_from_env(ENCRYPTION_KEY_ENV)

    def _fernet(self, salt: bytes) -> Fernet:
        """Derive encryption key from password"""
        kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=self.ITERATIONS)
        return Fernet(base64.urlsafe_b64encode(kdf.derive(self.password)))

    def encrypt_bytes(self, data: bytes) -> bytes:
        salt = secrets.token_bytes(16)
        return self.MAGIC + salt + self._fernet(salt).encrypt(data)

    def decrypt_bytes(self, blob: bytes) -> bytes:
        if not blob.startswith(self.MAGIC):
            raise ValueError("Not a medical cart encrypted file")
        salt = blob[len(self.MAGIC):len(self.MAGIC) + 16]
        return self._fernet(salt).decrypt(blob[len(self.MAGIC) + 16:])

    def encrypt_data(self, data: str) -> str:
        """Encrypt string data"""
        return base64.urlsafe_b64encode(self.encrypt_bytes(data.encode())).decode()

    def decrypt_data(self, encrypted_data: str) -> str:
        """Decrypt string data"""
        return self.decrypt_bytes(base64.urlsafe_b64decode(encrypted_data.encode())).decode()

    def encrypt_to_file(self, data: bytes, output_path: Path) -> Dict[str, Any]:
        """Encrypt bytes straight to a file (no plaintext on disk) and check it decrypts back"""
        blob = self.encrypt_bytes(data)
        with open(output_path, 'wb') as f:
            f.write(blob)
        with open(output_path, 'rb') as f:
            roundtrip = self.decrypt_bytes(f.read()) == data
        return {'encrypted_sha256': hashlib.sha256(blob).hexdigest(),
                'plaintext_sha256': hashlib.sha256(data).hexdigest(),
                'roundtrip_verified': roundtrip}

    def encrypt_file(self, file_path: Path, output_path: Path) -> str:
        """Encrypt file and return hash"""
        with open(file_path, 'rb') as f:
            return self.encrypt_to_file(f.read(), output_path)['encrypted_sha256']


class AccessControl:
    """Role-based access control system"""

    def __init__(self):
        # What each role may do with each kind of data
        rw, r = {'read', 'write'}, {'read'}
        self.data_permissions = {
            SecurityRole.ADMIN: {'healthcare_data': rw, 'barcode_data': rw, 'navigation_data': rw, 'telemetry_data': rw},
            SecurityRole.MEDICAL_STAFF: {'healthcare_data': rw, 'barcode_data': r, 'navigation_data': r, 'telemetry_data': r},
            SecurityRole.CART_OPERATOR: {'barcode_data': rw, 'navigation_data': rw, 'telemetry_data': rw},
            SecurityRole.AUDITOR: {'barcode_data': r, 'navigation_data': r, 'telemetry_data': r},
        }
        # Who may run the governance audit
        self.audit_roles = {SecurityRole.ADMIN, SecurityRole.MEDICAL_STAFF, SecurityRole.AUDITOR}

    @property
    def role_permissions(self) -> Dict[str, List[str]]:
        """Actions per role, for display"""
        return {role: sorted({a for actions in data.values() for a in actions} |
                             ({'audit'} if role in self.audit_roles else set()))
                for role, data in self.data_permissions.items()}

    def check_permission(self, role: str, action: str, data_type: str) -> bool:
        """Check if role has permission for action on data type"""
        if action == 'audit':
            return role in self.audit_roles
        return action in self.data_permissions.get(role, {}).get(data_type, set())

    def get_access_log_entry(self, role: str, action: str, data_type: str, success: bool,
                             run_id: str = "") -> Dict[str, Any]:
        """Generate access log entry"""
        return {
            'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'run_id': run_id,
            'role': role,
            'action': action,
            'data_type': data_type,
            'success': success,
            'entry_id': str(uuid.uuid4())
        }


def pixelate(frame: np.ndarray, block: int = 8) -> np.ndarray:
    """Coarse blocks over the whole frame: nobody stays recognizable, detected or not"""
    h, w = frame.shape[:2]
    small = cv2.resize(frame, (max(1, w // block), max(1, h // block)), interpolation=cv2.INTER_AREA)
    return cv2.resize(small, (w, h), interpolation=cv2.INTER_NEAREST)


class SecurityModule:
    """Main security module coordinator"""

    def __init__(self, architecture: PipelineArchitecture):
        self.arch = architecture
        self.phi_redactor = PHIRedactor()
        self.encryption = DataEncryption()
        self.access_control = AccessControl()
        self.secure_staging_path = architecture.staged_path / "secure"
        self.secure_staging_path.mkdir(exist_ok=True)
        self.encrypted_outputs: List[Dict[str, Any]] = []
        self.phi_checks: Dict[str, Any] = {}

        # Initialize access log (shared by all runs; entries carry their run_id)
        self.access_log_path = self.arch.workspace_path / "access_log.json"
        if not self.access_log_path.exists():
            with open(self.access_log_path, 'w') as f:
                json.dump([], f)

    def authorize(self, role: str, action: str, data_type: str) -> bool:
        """Check a permission and log the decision, granted or denied"""
        allowed = self.access_control.check_permission(role, action, data_type)
        self._log_access(self.access_control.get_access_log_entry(role, action, data_type, allowed,
                                                                  self.arch.run_id))
        if not allowed:
            logger.warning(f"Access denied: role {role} may not {action} {data_type}")
        return allowed

    def secure_healthcare_data(self, df: pd.DataFrame, user_role: str = SecurityRole.MEDICAL_STAFF) -> Dict[str, Any]:
        """Redact, verify and encrypt the healthcare records"""
        logger.info("Applying security measures to healthcare data")

        # Check permissions
        if not self.authorize(user_role, 'write', 'healthcare_data'):
            return {'status': 'denied', 'reason': f"role {user_role} may not write healthcare_data"}

        # Redact PHI, then check that nothing identifying is left
        df_redacted, redaction_log = self.phi_redactor.redact_dataframe(df)
        verification = self.phi_redactor.verify_redaction(df, df_redacted)
        k_anonymity = self.phi_redactor.k_anonymity(df_redacted)
        self.phi_checks['healthcare'] = verification
        self.phi_checks['k_anonymity'] = k_anonymity

        # Write the redacted records only in encrypted form
        encrypted_file = self.secure_staging_path / "healthcare_redacted.csv.enc"
        encryption = self.encryption.encrypt_to_file(df_redacted.to_csv(index=False).encode(), encrypted_file)
        self.encrypted_outputs.append({'file': self.arch.relative(encrypted_file), **encryption})

        # Record security lineage events
        self.arch.record_lineage_event(new_event(
            ProcessingStage.PHI_REDACTION, DataModality.HEALTHCARE_CSV,
            encryption['plaintext_sha256'],
            {'redaction_log': redaction_log, 'verification': verification, 'k_anonymity': k_anonymity,
             'user_role': user_role, 'records_out': int(len(df_redacted))}))
        self.arch.record_lineage_event(new_event(
            ProcessingStage.ENCRYPTION, DataModality.HEALTHCARE_CSV, encryption['encrypted_sha256'],
            {'encrypted_file': self.arch.relative(encrypted_file), 'key_source': self.encryption.key_source,
             'roundtrip_verified': encryption['roundtrip_verified'], 'user_role': user_role}))

        logger.info(f"Healthcare data redacted ({verification['status']}) and encrypted")

        return {
            'status': 'success' if verification['status'] == 'pass' else 'failed',
            'redacted_data': df_redacted,
            'redaction_log': redaction_log,
            'verification': verification,
            'k_anonymity': k_anonymity,
            'encrypted_file': str(encrypted_file),
            'encryption_hash': encryption['encrypted_sha256']
        }

    def screen_barcode_payloads(self, labels: List[Dict[str, Any]], user_role: str) -> Dict[str, Any]:
        """Quarantine labels whose payload carries personal data; drop those payloads from memory"""
        if not self.authorize(user_role, 'read', 'barcode_data'):
            for label in labels:
                label.pop('payload', None)
            return {'status': 'denied', 'reason': f"role {user_role} may not read barcode_data"}

        screened = []
        for label in labels:
            if not label.get('decoded'):
                continue
            found = self.phi_redactor.scan_text(label['payload'])
            label['phi_categories'] = sorted(found)
            label['quarantined'] = bool(found)
            if found:
                label['payload'] = None   # never kept, staged or reported
            screened.append({'file': label['file'], 'format': label['format'],
                             'quarantined': label['quarantined'], 'phi_categories': label['phi_categories']})

        quarantined = [s for s in screened if s['quarantined']]
        self.phi_checks['barcodes'] = {'labels_screened': len(screened), 'quarantined': len(quarantined)}
        self.arch.record_lineage_event(new_event(
            ProcessingStage.PHI_REDACTION, DataModality.BARCODE_IMAGE,
            hashlib.sha256(json.dumps(screened, sort_keys=True).encode()).hexdigest(),
            {'screened': screened, 'user_role': user_role}))
        if quarantined:
            logger.warning(f"{len(quarantined)} barcode label(s) carry personal data and were quarantined: "
                           + ", ".join(f"{q['file']} ({', '.join(q['phi_categories'])})" for q in quarantined))
        return {'status': 'success', 'screened': screened}

    def secure_non_phi_data(self, data_type: str, data_path: Path, user_role: str) -> Dict[str, Any]:
        """Keep an encrypted copy of a staged file (needs write access to that data)"""
        logger.info(f"Applying security to {data_type}")

        # Check permissions
        if not self.authorize(user_role, 'write', data_type):
            return {'status': 'skipped', 'reason': f"role {user_role} has no write access to {data_type}"}

        encrypted_file = self.secure_staging_path / f"{Path(data_path).name}.enc"
        with open(data_path, 'rb') as f:
            encryption = self.encryption.encrypt_to_file(f.read(), encrypted_file)
        self.encrypted_outputs.append({'file': self.arch.relative(encrypted_file), **encryption})

        modality = {'barcode_data': DataModality.BARCODE_IMAGE, 'navigation_data': DataModality.VIDEO_FRAME,
                    'telemetry_data': DataModality.MHEALTH_TELEMETRY}[data_type]
        self.arch.record_lineage_event(new_event(
            ProcessingStage.ENCRYPTION, modality, encryption['encrypted_sha256'],
            {'data_type': data_type, 'source_file': self.arch.relative(data_path),
             'encrypted_file': self.arch.relative(encrypted_file), 'key_source': self.encryption.key_source,
             'roundtrip_verified': encryption['roundtrip_verified'], 'user_role': user_role}))

        return {
            'status': 'success',
            'encrypted_file': str(encrypted_file),
            'encryption_hash': encryption['encrypted_sha256']
        }

    def _log_access(self, log_entry: Dict[str, Any]):
        """Append to access log"""
        try:
            with open(self.access_log_path, 'r') as f:
                access_log = json.load(f)
        except (OSError, json.JSONDecodeError):
            access_log = []

        access_log.append(log_entry)

        with open(self.access_log_path, 'w') as f:
            json.dump(access_log, f, indent=2)

    def run_access_log(self) -> List[Dict[str, Any]]:
        try:
            with open(self.access_log_path, 'r') as f:
                return [e for e in json.load(f) if e.get('run_id') == self.arch.run_id]
        except (OSError, json.JSONDecodeError):
            return []

    def generate_security_audit(self) -> Dict[str, Any]:
        """Security audit of this run"""

        access_log = self.run_access_log()
        denied = [e for e in access_log if not e['success']]
        role_access_count, data_type_access_count = {}, {}
        for entry in access_log:
            role_access_count[entry['role']] = role_access_count.get(entry['role'], 0) + 1
            data_type_access_count[entry['data_type']] = data_type_access_count.get(entry['data_type'], 0) + 1

        # Encryption: every file decrypts back, and with a key someone keeps
        roundtrips_ok = all(e['roundtrip_verified'] for e in self.encrypted_outputs)
        if not self.encrypted_outputs:
            encryption_status, encryption_note = 'not_run', 'this role staged nothing that needed encrypting'
        elif not roundtrips_ok:
            encryption_status, encryption_note = 'fail', 'an encrypted file did not decrypt back to its content'
        elif self.encryption.key_source == 'one-time':
            encryption_status = 'warning'
            encryption_note = f'{ENCRYPTION_KEY_ENV} not set: one-time key, the files cannot be decrypted after this run'
        else:
            encryption_status, encryption_note = 'pass', 'each one decrypts back to its content'

        healthcare_check = self.phi_checks.get('healthcare')
        if healthcare_check is None:
            phi_status, phi_note = 'not_run', 'healthcare records were not processed'
        elif healthcare_check['status'] == 'pass':
            phi_status, phi_note = 'pass', 'no identifiers, contact details or exact dates left'
        else:
            phi_status, phi_note = 'fail', 'identifying values survived redaction'

        audit_results = {
            'access_control': {
                'total_access_attempts': len(access_log),
                'failed_access_attempts': len(denied),
                'denied': [f"{e['role']} {e['action']} {e['data_type']}" for e in denied],
                'role_access_distribution': role_access_count,
                'data_type_access_distribution': data_type_access_count,
                # Denials are the policy working; a stage they blocked shows up in its own check
                'status': 'pass'
            },
            'encryption': {
                'encrypted_files_count': len(self.encrypted_outputs),
                'encrypted_files': self.encrypted_outputs,
                'key_source': self.encryption.key_source,
                'kdf': f'PBKDF2-HMAC-SHA256, {DataEncryption.ITERATIONS} iterations, random salt per file',
                'status': encryption_status,
                'note': encryption_note
            },
            'phi_protection': {
                'redaction_applied': healthcare_check is not None,
                'verification': healthcare_check,
                'k_anonymity': self.phi_checks.get('k_anonymity'),
                'barcode_screening': self.phi_checks.get('barcodes'),
                'pseudonym_key_source': self.phi_redactor.key_source,
                'status': phi_status,
                'note': phi_note
            },
            'audit_timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat()
        }

        statuses = [audit_results[k]['status'] for k in ('access_control', 'encryption', 'phi_protection')]
        audit_results['overall_security_status'] = ('fail' if 'fail' in statuses else
                                                    'warning' if {'warning', 'not_run'} & set(statuses) else 'pass')
        return audit_results


def decrypt_file_cli(path: str):
    """python security_module.py decrypt FILE.enc  -> plaintext on stdout"""
    if not os.environ.get(ENCRYPTION_KEY_ENV):
        sys.exit(f"Set {ENCRYPTION_KEY_ENV} to the passphrase the file was encrypted with")
    with open(path, 'rb') as f:
        blob = f.read()
    try:
        sys.stdout.buffer.write(DataEncryption().decrypt_bytes(blob))
    except BrokenPipeError:   # e.g. piped into head
        pass
    except InvalidToken:
        sys.exit("Wrong key: the file was encrypted with a different passphrase (or changed since)")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == 'decrypt':
        decrypt_file_cli(sys.argv[2])
    else:
        print(__doc__)
