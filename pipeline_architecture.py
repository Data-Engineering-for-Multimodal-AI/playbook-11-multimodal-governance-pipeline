"""
Multimodal Data Pipeline for Autonomous Medical Cart
Architecture Design and Core Components

This module defines the overall architecture for the medical cart pipeline
including ingestion, governance, security, inference, and responsible AI components.

Lineage is an append-only ledger in SQLite. Each event's hash covers every field of the
event (metadata included) and the hash of the event before it, so editing, deleting or
reordering any recorded event breaks the chain, and validate_lineage_integrity() finds where.
"""

import os
import sqlite3
import hashlib
import json
import logging
import datetime
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict
from enum import Enum

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent
GENESIS = "genesis"


class DataModality(Enum):
    """Supported data modalities"""
    HEALTHCARE_CSV = "healthcare_csv"
    BARCODE_IMAGE = "barcode_image"
    VIDEO_FRAME = "video_frame"
    MHEALTH_TELEMETRY = "mhealth_telemetry"


class ProcessingStage(Enum):
    """Processing pipeline stages"""
    INGESTION = "ingestion"
    VALIDATION = "validation"
    PHI_REDACTION = "phi_redaction"
    ENCRYPTION = "encryption"
    INFERENCE = "inference"
    AUDIT = "audit"


@dataclass
class LineageEvent:
    """Immutable lineage event for governance tracking"""
    event_id: str
    timestamp: str
    stage: ProcessingStage
    modality: DataModality
    data_hash: str
    previous_hash: str
    metadata: Dict[str, Any]
    run_id: str = ""
    seq: int = 0

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d['stage'], d['modality'] = self.stage.value, self.modality.value
        return d

    def compute_hash(self) -> str:
        """SHA-256 over every field, metadata and the previous event's hash included"""
        return event_hash(self.to_dict())


def event_hash(event: Dict[str, Any]) -> str:
    """Hash of a stored or new event (a dict with the LineageEvent fields)."""
    content = {k: event[k] for k in ('seq', 'event_id', 'run_id', 'timestamp', 'stage', 'modality',
                                     'data_hash', 'previous_hash')}
    metadata = event['metadata']
    content['metadata'] = json.loads(metadata) if isinstance(metadata, str) else metadata
    canonical = json.dumps(content, sort_keys=True, separators=(',', ':'), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def new_event(stage: ProcessingStage, modality: DataModality, data_hash: str,
              metadata: Dict[str, Any]) -> LineageEvent:
    """An event ready to record; the ledger fills in seq, run and previous hash."""
    return LineageEvent(event_id=str(uuid.uuid4()),
                        timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                        stage=stage, modality=modality, data_hash=data_hash,
                        previous_hash="", metadata=metadata)


class PipelineArchitecture:
    """Main pipeline architecture coordinator"""

    def __init__(self, workspace_path: str, run_id: Optional[str] = None):
        self.workspace_path = Path(workspace_path).resolve()
        self.data_path = self.workspace_path / "sample-data"
        self.reports_path = self.workspace_path / "reports"
        self.staged_path = self.workspace_path / "staged_data"
        self.db_path = self.workspace_path / "governance.db"
        self.run_id = run_id or (datetime.datetime.now().strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:6])

        if not self.data_path.is_dir():
            raise FileNotFoundError(f"No sample-data folder in {self.workspace_path}")

        # Create directories
        self.reports_path.mkdir(exist_ok=True)
        self.staged_path.mkdir(exist_ok=True)

        # Initialize governance database
        self._init_governance_db()

    def relative(self, path) -> str:
        """Paths in lineage and reports are relative to the workspace (no home folders in audit records)."""
        try:
            return str(Path(path).resolve().relative_to(self.workspace_path))
        except ValueError:
            return str(path)

    @contextmanager
    def _connect(self):
        """A connection that commits on success, rolls back on error, and closes."""
        conn = sqlite3.connect(self.db_path)
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_governance_db(self):
        """Initialize SQLite database for governance tracking"""
        with self._connect() as conn:
            columns = [row[1] for row in conn.execute("PRAGMA table_info(lineage_events)")]
            if columns and 'seq' not in columns:
                # A database from the first edition: keep it for reference and start a new ledger
                conn.execute("ALTER TABLE lineage_events RENAME TO lineage_events_first_edition")
                logger.warning("Kept the first-edition lineage table as lineage_events_first_edition")

            # Lineage events, in the order they were recorded (seq)
            conn.execute('''
                CREATE TABLE IF NOT EXISTS lineage_events (
                    seq INTEGER PRIMARY KEY,
                    event_id TEXT UNIQUE NOT NULL,
                    run_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    modality TEXT NOT NULL,
                    data_hash TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    event_hash TEXT NOT NULL,
                    metadata TEXT NOT NULL
                )
            ''')

            # Prescription tracking: one row per medication and run
            conn.execute('''
                CREATE TABLE IF NOT EXISTS prescription_tracking (
                    prescription_id TEXT PRIMARY KEY,
                    patient_id TEXT,
                    medication TEXT,
                    barcode_match TEXT,
                    delivery_status TEXT,
                    created_at TEXT,
                    updated_at TEXT
                )
            ''')
        logger.debug("Governance database initialized")

    def record_lineage_event(self, event: LineageEvent) -> str:
        """Append an event to the hash chain; returns its hash"""
        event.run_id = self.run_id
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")   # no other writer between reading the tip and appending
            last = conn.execute("SELECT seq, event_hash FROM lineage_events ORDER BY seq DESC LIMIT 1").fetchone()
            event.seq = last[0] + 1 if last else 1
            event.previous_hash = last[1] if last else GENESIS
            event_hash_value = event.compute_hash()
            conn.execute('''
                INSERT INTO lineage_events
                (seq, event_id, run_id, timestamp, stage, modality, data_hash, previous_hash, event_hash, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (event.seq, event.event_id, event.run_id, event.timestamp, event.stage.value,
                  event.modality.value, event.data_hash, event.previous_hash, event_hash_value,
                  json.dumps(event.metadata, sort_keys=True, default=str)))

        logger.debug(f"Recorded lineage event {event.seq}: {event.stage.value}/{event.modality.value}")
        return event_hash_value

    def get_lineage_chain(self, run_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Retrieve the lineage chain (or one run's events) in recorded order"""
        with self._connect() as conn:
            cursor = conn.execute("SELECT * FROM lineage_events ORDER BY seq ASC")
            columns = [desc[0] for desc in cursor.description]
            events = [dict(zip(columns, row)) for row in cursor.fetchall()]
        if run_id:
            events = [e for e in events if e['run_id'] == run_id]
        return events

    def verify_lineage(self) -> Dict[str, Any]:
        """Recompute every hash and link; report the first event that doesn't verify"""
        return verify_chain(self.get_lineage_chain())

    def validate_lineage_integrity(self) -> bool:
        """Validate hash chain integrity"""
        result = self.verify_lineage()
        if result['valid']:
            logger.info(f"Lineage integrity verified: {result['events_checked']} events")
        else:
            logger.error(f"Hash chain integrity violation at event {result['first_bad_seq']}: {result['problem']}")
        return result['valid']


def verify_chain(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Check a chain of stored events (ordered by seq)."""
    previous = GENESIS
    for expected_seq, event in enumerate(events, start=1):
        problem = None
        if event['seq'] != expected_seq:
            problem = f"sequence gap: expected event {expected_seq}, found {event['seq']}"
        elif event['previous_hash'] != previous:
            problem = "link to the previous event doesn't match"
        elif event_hash(event) != event['event_hash']:
            problem = "content changed after it was recorded"
        if problem:
            return {'valid': False, 'events_checked': expected_seq, 'first_bad_seq': event['seq'],
                    'problem': problem}
        previous = event['event_hash']
    return {'valid': True, 'events_checked': len(events), 'first_bad_seq': None, 'problem': None}


if __name__ == "__main__":
    # Verify the ledger in this folder
    logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')
    arch = PipelineArchitecture(os.environ.get("MEDICAL_CART_WORKSPACE", REPO_ROOT))
    print(json.dumps(arch.verify_lineage(), indent=2))
