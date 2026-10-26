#!/usr/bin/env python3
"""
Verify the lineage ledger (governance.db), or watch it catch tampering.

    python verify_lineage.py                 # recompute every hash; exit 1 if the chain is broken
    python verify_lineage.py --tamper-demo   # edit, re-hash and delete events in a copy, and verify each time

The demo works on a temporary copy; governance.db itself is never changed.
"""
import argparse
import json
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

from pipeline_architecture import REPO_ROOT, event_hash, verify_chain


def load(db: Path):
    with sqlite3.connect(db) as conn:
        cursor = conn.execute("SELECT * FROM lineage_events ORDER BY seq")
        columns = [d[0] for d in cursor.description]
        events = [dict(zip(columns, row)) for row in cursor.fetchall()]
    conn.close()
    return events


def report(label: str, db: Path) -> bool:
    result = verify_chain(load(db))
    if result['valid']:
        print(f"{label}: VALID ({result['events_checked']} events recomputed)")
    else:
        print(f"{label}: BROKEN at event {result['first_bad_seq']} - {result['problem']}")
    return result['valid']


def tamper_demo(db: Path):
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "governance.db"
        shutil.copy(db, copy)
        events = load(copy)
        if len(events) < 3:
            sys.exit("Run the pipeline first: the ledger needs a few events")
        report("1. Ledger as recorded", copy)

        # Pick the PHI redaction event if there is one: the record an auditor relies on
        target = next((e for e in events if e['stage'] == 'phi_redaction'), events[len(events) // 2])
        metadata = json.loads(target['metadata'])
        conn = sqlite3.connect(copy)

        # 2. Change what the event says (e.g. hide that a check failed)
        metadata['tampered'] = True
        if 'verification' in metadata:
            metadata['verification']['residual_identifiers'] = 0
            metadata['verification']['status'] = 'pass'
        conn.execute("UPDATE lineage_events SET metadata = ? WHERE seq = ?",
                     (json.dumps(metadata, sort_keys=True), target['seq']))
        conn.commit()
        print(f"\n   Edited the metadata of event {target['seq']} ({target['stage']}/{target['modality']})")
        report("2. After editing", copy)

        # 3. Cover it up: recompute that event's hash too
        edited = next(e for e in load(copy) if e['seq'] == target['seq'])
        conn.execute("UPDATE lineage_events SET event_hash = ? WHERE seq = ?", (event_hash(edited), target['seq']))
        conn.commit()
        print(f"\n   Recomputed event {target['seq']}'s hash to match the edit")
        report("3. After re-hashing it", copy)

        # 4. Remove an event instead
        shutil.copy(db, copy)
        conn.close()
        conn = sqlite3.connect(copy)
        conn.execute("DELETE FROM lineage_events WHERE seq = ?", (target['seq'],))
        conn.commit()
        conn.close()
        print(f"\n   Deleted event {target['seq']} from a fresh copy")
        report("4. After deleting", copy)
        print("\nOnly rewriting every later event as well would hide an edit; keep a copy of the latest "
              "event hash somewhere else (a signed log, a ticket) to catch that.")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--workspace', default=str(REPO_ROOT))
    parser.add_argument('--tamper-demo', action='store_true')
    args = parser.parse_args()

    db = Path(args.workspace) / "governance.db"
    if not db.exists():
        sys.exit(f"No ledger at {db}: run python medical_cart_pipeline.py first")
    if args.tamper_demo:
        tamper_demo(db)
    else:
        sys.exit(0 if report("Lineage ledger", db) else 1)


if __name__ == "__main__":
    main()
