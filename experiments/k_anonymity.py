"""Try this 1: how coarse must the records be before nobody stands out? (make try-k-anonymity)

After redaction there are no names, but a record can still be singled out by what an
outsider may know: age, gender, admission year, blood type. k is the size of the smallest
group of records that share those values; the pipeline warns when k < 5. This redacts the
sample records once, as the pipeline does, then measures k for coarser and finer versions of
the quasi-identifiers. Nothing is written.

Change VARIANTS and run it again.
"""

import logging
import os
import sys

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
logging.disable(logging.WARNING)
from security_module import PHIRedactor  # noqa: E402

BASE = ["Age", "Gender", "Admission Year", "Blood Type"]


def ten_year_age(df):
    raw = df["_age"]
    return (raw // 10 * 10).astype(int).astype(str) + "s"


def five_year_period(df):
    return (df["Admission Year"] // 5 * 5).astype(str) + "-" + (df["Admission Year"] // 5 * 5 + 4).astype(str)


VARIANTS = [
    ("as the pipeline redacts", BASE, {}),
    ("+ medical condition", BASE + ["Medical Condition"], {}),
    ("+ insurance provider", BASE + ["Insurance Provider"], {}),
    ("age in 10-year bands", BASE, {"Age": ten_year_age}),
    ("without blood type", ["Age", "Gender", "Admission Year"], {}),
    ("admission in 5-year periods", BASE, {"Admission Year": five_year_period}),
    ("both of the last two", ["Age", "Gender", "Admission Year"], {"Admission Year": five_year_period}),
]


def main():
    raw = pd.read_csv(os.path.join(ROOT, "sample-data", "healthcare_dataset.csv"))
    redactor = PHIRedactor(pseudonym_key=b"try-this")
    redacted, _ = redactor.redact_dataframe(raw)
    redacted["_age"] = raw.drop_duplicates().reset_index(drop=True)["Age"]
    print(f"{len(redacted)} redacted records (exact duplicates dropped).\n")
    print(f"{'quasi-identifiers':30} {'groups':>7} {'k':>4} {'records in groups under 5':>26}")
    for label, columns, changes in VARIANTS:
        df = redacted.copy()
        for column, change in changes.items():
            df[column] = change(df)
        r = redactor.k_anonymity(df, quasi_identifiers=tuple(columns))
        print(f"{label:30} {r['groups']:>7} {r['k']:>4} {r['records_in_groups_under_5']:>26}")
    print(f"\nThe pipeline's quasi-identifiers: {', '.join(BASE)} (age in its 5 bands).")


if __name__ == "__main__":
    main()
