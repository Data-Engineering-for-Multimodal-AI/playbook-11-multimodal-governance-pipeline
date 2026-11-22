"""Try this 3: can the motion monitor be made robust to a noisy sensor? (make try-sensor-noise)

The motion monitor reads a 2-second window as "still" when the chest acceleration varies less
than a threshold fitted on subjects 1-5 (0.2355 m/s^2), and is scored on subjects 6-10. The
pipeline's stress test adds sensor noise to the test subjects and keeps the threshold: with
noise of 0.5 m/s^2 it drops to chance (0.500). This fits the threshold a second way, on the
training subjects with noise added, and scores both thresholds at several noise levels.
Nothing is written.

Change TRAIN_NOISE or TEST_NOISE and run it again.
"""

import io
import logging
import os
import sys
import zipfile

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
logging.disable(logging.WARNING)
from data_ingestion import MHEALTH_COLUMNS, MHEALTH_ZIP  # noqa: E402
from inference_module import TelemetryAnalyzer  # noqa: E402

TRAIN_NOISE = [0.0, 0.2, 0.5]   # 0.0 is what the pipeline does
TEST_NOISE = [0.0, 0.1, 0.2, 0.5]


def load():
    """The ten subjects' logs, read from the zip as data_ingestion.py does (without the lineage record)."""
    data = {}
    with zipfile.ZipFile(os.path.join(ROOT, "sample-data", MHEALTH_ZIP)) as archive:
        for name in archive.namelist():
            if name.endswith(".log") and "mHealth_subject" in name:
                with archive.open(name) as f:
                    df = pd.read_csv(io.TextIOWrapper(f), sep=r"\s+", header=None)
                df.columns = MHEALTH_COLUMNS
                data[os.path.basename(name)[len("mHealth_subject"):-4]] = df
    return data


def main():
    data = load()
    monitor = TelemetryAnalyzer()
    train = [s for s in data if s in monitor.train_subjects]
    test = sorted((s for s in data if s not in monitor.train_subjects), key=int)

    def features(subjects, noise):
        f, a = zip(*(monitor.windows(data[s], noise=noise) for s in subjects))
        return np.concatenate(f), np.concatenate(a)

    print(f"Balanced accuracy on held-out subjects {', '.join(test)} (0.5 is chance).\n")
    header = "".join(f"{'test noise ' + str(n):>15}" for n in TEST_NOISE)
    print(f"{'threshold fitted on':30} {'threshold':>9}{header}")
    for train_noise in TRAIN_NOISE:
        threshold = monitor.fit_threshold(*features(train, train_noise))
        scores = [monitor.balanced_accuracy(f < threshold, a)
                  for f, a in (features(test, n) for n in TEST_NOISE)]
        label = "clean data (the pipeline)" if train_noise == 0 else f"data with noise {train_noise}"
        print(f"{label:30} {threshold:>9.4f}" + "".join(f"{s:>15.3f}" for s in scores))
    print("\nNoise: standard deviation in m/s^2, added to each axis of the chest accelerometer.")


if __name__ == "__main__":
    main()
