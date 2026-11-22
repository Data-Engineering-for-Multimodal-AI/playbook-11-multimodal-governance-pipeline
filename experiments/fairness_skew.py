"""Try this 2: when does the fairness check notice an uneven gap? (make try-fairness-skew)

The cart can verify a prescription by its label for 4 of the 5 medications; Lipitor has no
label, so its prescriptions need a manual check. The fairness check compares the share of
prescriptions verified automatically across patient groups (age band, gender, condition,
insurer) and passes while the largest gap is under 10 points and the lowest ratio at least
0.8 (the four-fifths rule). In the sample, Lipitor is spread evenly, so the gap is 1.2%.
This moves more of one group's prescriptions to Lipitor, step by step, and reruns the same
check. Nothing is written.

Change GROUP or SHARES and run it again.
"""

import logging
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
logging.disable(logging.WARNING)
from responsible_ai import BiasDetector  # noqa: E402
from security_module import PHIRedactor  # noqa: E402

GROUP = ("Age", "70+")
SHARES = [None, 0.25, 0.30, 0.35, 0.40, 0.50]   # None: the data as it is
VERIFIED = ["Aspirin", "Ibuprofen", "Paracetamol", "Penicillin"]   # the labels the pipeline verifies


def main():
    raw = pd.read_csv(os.path.join(ROOT, "sample-data", "healthcare_dataset.csv"))
    redacted, _ = PHIRedactor(pseudonym_key=b"try-this").redact_dataframe(raw)
    column, value = GROUP
    in_group = redacted[column] == value
    rng = np.random.default_rng(0)
    detector = BiasDetector()
    results = {"prescription_matching": {"auto_verified_medications": VERIFIED}}
    print(f"Group: {column} {value} ({int(in_group.sum())} records). Others keep their prescriptions.\n")
    print(f"{'Lipitor share in group':>22} {'group verified':>15} {'others verified':>16} "
          f"{'largest gap':>12} {'lowest ratio':>13}  verdict")
    for share in SHARES:
        df = redacted.copy()
        if share is not None:
            idx = df.index[in_group]
            lipitor = rng.random(len(idx)) < share
            # keep the others' medications; give the group Lipitor with probability `share`
            others = df.loc[idx, "Medication"].where(df.loc[idx, "Medication"] != "Lipitor",
                                                     rng.choice(VERIFIED, len(idx)))
            df.loc[idx, "Medication"] = np.where(lipitor, "Lipitor", others)
        r = detector.analyze_demographic_bias(df, results)
        verified = df["Medication"].isin(VERIFIED)
        actual = (df.loc[in_group, "Medication"] == "Lipitor").mean()
        label = f"{actual:.0%}" + (" (as is)" if share is None else "")
        verdict = {"low_bias": "pass", "moderate_bias": "warning", "high_bias": "fail"}[r["bias_status"]]
        print(f"{label:>22} {verified[in_group].mean():>15.1%} {verified[~in_group].mean():>16.1%} "
              f"{r['overall_bias_score']:>12.1%} {r['min_disparate_impact_ratio']:>13.3f}  {verdict}")
    print("\npass: gap under 10 points and ratio at least 0.8; warning: gap under 20 points; fail: otherwise.")


if __name__ == "__main__":
    main()
