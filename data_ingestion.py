"""
Data Ingestion Module for Multimodal Medical Cart Pipeline

Handles loading and validation of all data modalities:
- Healthcare CSV (EHR-like records)
- Barcode images (various formats), decoded with zxing-cpp
- Video frames (the cart's camera view)
- MHealth telemetry (sensor data), read straight from the dataset zip

Nothing that holds patient data is written in plaintext here: the records stay in memory
until the security stage has redacted them, and barcode payloads are staged only as hashes.
"""

import io
import json
import hashlib
import zipfile
import datetime
import logging
from pathlib import Path
from typing import Dict, Any, Optional

import cv2
import numpy as np
import pandas as pd
import zxingcpp

from pipeline_architecture import PipelineArchitecture, ProcessingStage, DataModality, new_event, REPO_ROOT

logger = logging.getLogger(__name__)

# MHEALTH column layout (sample-data/MHEALTHDATASET/README.txt)
MHEALTH_COLUMNS = [
    'chest_acc_x', 'chest_acc_y', 'chest_acc_z',
    'ecg_lead1', 'ecg_lead2',
    'ankle_acc_x', 'ankle_acc_y', 'ankle_acc_z',
    'ankle_gyro_x', 'ankle_gyro_y', 'ankle_gyro_z',
    'ankle_mag_x', 'ankle_mag_y', 'ankle_mag_z',
    'arm_acc_x', 'arm_acc_y', 'arm_acc_z',
    'arm_gyro_x', 'arm_gyro_y', 'arm_gyro_z',
    'arm_mag_x', 'arm_mag_y', 'arm_mag_z',
    'activity_label'
]
MHEALTH_ZIP = "mhealth+dataset.zip"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, 'rb') as f:
        while chunk := f.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


class DataIngestionModule:
    """Handles ingestion of multimodal data with validation and staging"""

    def __init__(self, architecture: PipelineArchitecture):
        self.arch = architecture
        self.staging_path = architecture.staged_path

    def compute_data_hash(self, data: Any) -> str:
        """Compute hash for data integrity verification"""
        if isinstance(data, pd.DataFrame):
            return hashlib.sha256(pd.util.hash_pandas_object(data, index=False).values.tobytes()).hexdigest()
        elif isinstance(data, np.ndarray):
            return hashlib.sha256(np.ascontiguousarray(data).tobytes()).hexdigest()
        elif isinstance(data, bytes):
            return hashlib.sha256(data).hexdigest()
        else:
            return hashlib.sha256(str(data).encode()).hexdigest()

    def _record(self, modality: DataModality, data_hash: str, metadata: Dict[str, Any]):
        self.arch.record_lineage_event(new_event(ProcessingStage.INGESTION, modality, data_hash, metadata))

    def _stage_json(self, name: str, content: Any) -> Path:
        path = self.staging_path / name
        with open(path, 'w') as f:
            json.dump(content, f, indent=2, default=str)
        return path

    def ingest_healthcare_csv(self) -> Dict[str, Any]:
        """Ingest and validate healthcare CSV data"""
        logger.info("Starting healthcare CSV ingestion")

        csv_path = self.arch.data_path / "healthcare_dataset.csv"

        try:
            # Load CSV with validation
            df = pd.read_csv(csv_path)

            # Basic validation
            required_columns = ['Name', 'Age', 'Gender', 'Medical Condition', 'Medication',
                                'Doctor', 'Date of Admission', 'Discharge Date']
            missing_cols = [col for col in required_columns if col not in df.columns]

            if missing_cols:
                raise ValueError(f"Missing required columns: {missing_cols}")

            admitted = pd.to_datetime(df['Date of Admission'], errors='coerce')
            discharged = pd.to_datetime(df['Discharge Date'], errors='coerce')

            # Data quality checks (plain ints so they serialize)
            validation_results = {
                'total_records': int(len(df)),
                'exact_duplicate_records': int(df.duplicated().sum()),
                'missing_names': int(df['Name'].isna().sum()),
                'invalid_ages': int(((df['Age'] < 0) | (df['Age'] > 120)).sum()),
                'missing_medications': int(df['Medication'].isna().sum()),
                'unparseable_dates': int(admitted.isna().sum() + discharged.isna().sum()),
                'discharge_before_admission': int((discharged < admitted).sum()),
                'phi_fields_detected': ['Name', 'Doctor', 'Date of Admission', 'Discharge Date', 'Age']
            }

            # The raw records stay in memory: the security stage writes only the redacted, encrypted copy
            source_hash = sha256_file(csv_path)
            self._record(DataModality.HEALTHCARE_CSV, source_hash, {
                'source_file': self.arch.relative(csv_path),
                'source_sha256': source_hash,
                'validation_results': validation_results,
                'staged_file': None,
            })

            logger.info(f"Healthcare CSV ingestion completed: {len(df)} records")
            return {
                'status': 'success',
                'data': df,
                'validation': validation_results,
                'staged_file': None
            }

        except Exception as e:
            logger.error(f"Healthcare CSV ingestion failed: {str(e)}")
            return {'status': 'error', 'error': str(e)}

    def ingest_barcode_images(self) -> Dict[str, Any]:
        """Decode and validate barcode images"""
        logger.info("Starting barcode image ingestion")

        barcode_path = self.arch.data_path / "bar-codes"

        try:
            labels = []
            validation_results = {
                'total_images': 0,
                'decoded_images': 0,
                'undecodable_images': 0,
                'formats_detected': []
            }

            for image_file in sorted(barcode_path.glob("*.png")):
                validation_results['total_images'] += 1
                img = cv2.imread(str(image_file))
                if img is None:
                    validation_results['undecodable_images'] += 1
                    logger.warning(f"Can't read image {image_file.name}")
                    continue

                results = zxingcpp.read_barcodes(img)
                if not results:
                    validation_results['undecodable_images'] += 1
                    labels.append({'file': image_file.name, 'decoded': False})
                    continue

                code = results[0]
                labels.append({
                    'file': image_file.name,
                    'decoded': True,
                    'format': str(code.format),
                    'valid': bool(code.valid),
                    'payload': code.text,   # in memory only; classified by the security stage
                    'payload_sha256': hashlib.sha256(code.text.encode()).hexdigest(),
                    'payload_length': len(code.text),
                    'image': img,
                })
                validation_results['decoded_images'] += 1
                validation_results['formats_detected'].append(str(code.format))

            # Stage what was scanned, without the payloads (or their hashes: a payload may hold personal data)
            staged = [{k: v for k, v in label.items() if k not in ('payload', 'payload_sha256', 'image')}
                      for label in labels]
            staged_file = self._stage_json("barcode_scans.json", staged)

            self._record(DataModality.BARCODE_IMAGE, self.compute_data_hash(json.dumps(staged, sort_keys=True)), {
                'source_path': self.arch.relative(barcode_path),
                'source_sha256': {p.name: sha256_file(p) for p in sorted(barcode_path.glob("*.png"))},
                'staged_file': self.arch.relative(staged_file),
                'validation_results': validation_results
            })

            logger.info(f"Barcode ingestion completed: {validation_results['decoded_images']} of "
                        f"{validation_results['total_images']} images decoded")
            return {
                'status': 'success' if validation_results['decoded_images'] else 'error',
                'data': labels,
                'validation': validation_results,
                'staged_file': str(staged_file)
            }

        except Exception as e:
            logger.error(f"Barcode ingestion failed: {str(e)}")
            return {'status': 'error', 'error': str(e)}

    def ingest_video_frames(self, max_frames: int = 20) -> Dict[str, Any]:
        """Sample frames from the cart camera video"""
        logger.info("Starting video frame ingestion")

        video_path = self.arch.data_path / "samples_data_vtest.avi"

        try:
            cap = cv2.VideoCapture(str(video_path))
            if not cap.isOpened():
                raise ValueError(f"Cannot open video file: {video_path}")

            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            fps = cap.get(cv2.CAP_PROP_FPS)

            # Evenly spaced frames across the clip
            frame_interval = max(1, total_frames // max_frames)
            frames_data = []
            for frame_number in range(0, total_frames, frame_interval)[:max_frames]:
                cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
                ret, frame = cap.read()
                if not ret:
                    break
                frames_data.append({
                    'frame_number': frame_number,
                    'timestamp': round(frame_number / fps, 2),
                    'shape': list(frame.shape),
                    'hash': self.compute_data_hash(frame),
                    'frame': frame,   # in memory; keyframes are staged only pixelated
                })
            cap.release()

            validation_results = {
                'total_frames_in_video': total_frames,
                'frames_extracted': len(frames_data),
                'fps': fps,
                'duration_seconds': round(total_frames / fps, 1),
                'extraction_interval': frame_interval
            }

            metadata = [{k: v for k, v in f.items() if k != 'frame'} for f in frames_data]
            self._record(DataModality.VIDEO_FRAME, self.compute_data_hash(json.dumps(metadata, sort_keys=True)), {
                'source_file': self.arch.relative(video_path),
                'source_sha256': sha256_file(video_path),
                'validation_results': validation_results
            })

            logger.info(f"Video frame ingestion completed: {len(frames_data)} frames sampled")
            return {
                'status': 'success' if frames_data else 'error',
                'data': frames_data,
                'validation': validation_results,
                'staged_file': None
            }

        except Exception as e:
            logger.error(f"Video frame ingestion failed: {str(e)}")
            return {'status': 'error', 'error': str(e)}

    def ingest_mhealth_telemetry(self, sample_subjects: Optional[int] = None) -> Dict[str, Any]:
        """Read the MHEALTH sensor logs from the dataset zip"""
        logger.info("Starting MHealth telemetry ingestion")

        zip_path = self.arch.data_path / MHEALTH_ZIP

        try:
            telemetry_data = {}
            validation_results = {
                'total_subjects': 0,
                'valid_subjects': 0,
                'invalid_subjects': 0,
                'total_samples': 0,
                'missing_values': 0,
                'samples_per_activity': {}
            }

            with zipfile.ZipFile(zip_path) as archive:
                logs = sorted((n for n in archive.namelist() if n.endswith('.log') and 'mHealth_subject' in n),
                              key=lambda n: int(Path(n).stem.replace('mHealth_subject', '')))
                for name in logs[:sample_subjects]:
                    validation_results['total_subjects'] += 1
                    subject_id = Path(name).stem.replace('mHealth_subject', '')
                    with archive.open(name) as f:
                        df = pd.read_csv(io.TextIOWrapper(f), sep=r'\s+', header=None)
                    if len(df.columns) != len(MHEALTH_COLUMNS):
                        logger.warning(f"{name}: {len(df.columns)} columns, expected {len(MHEALTH_COLUMNS)}")
                        validation_results['invalid_subjects'] += 1
                        continue
                    df.columns = MHEALTH_COLUMNS
                    df['activity_label'] = df['activity_label'].astype(int)
                    telemetry_data[subject_id] = df

                    validation_results['valid_subjects'] += 1
                    validation_results['total_samples'] += len(df)
                    validation_results['missing_values'] += int(df.isna().sum().sum())
                    for activity, count in df['activity_label'].value_counts().items():
                        key = str(activity)
                        validation_results['samples_per_activity'][key] = (
                            validation_results['samples_per_activity'].get(key, 0) + int(count))

            self._record(DataModality.MHEALTH_TELEMETRY, sha256_file(zip_path), {
                'source_file': self.arch.relative(zip_path),
                'subjects': list(telemetry_data),
                'validation_results': validation_results
            })

            logger.info(f"MHealth telemetry ingestion completed: {validation_results['valid_subjects']} subjects, "
                        f"{validation_results['total_samples']} samples")
            return {
                'status': 'success' if telemetry_data else 'error',
                'data': telemetry_data,
                'validation': validation_results,
                'staged_file': None
            }

        except Exception as e:
            logger.error(f"MHealth telemetry ingestion failed: {str(e)}")
            return {'status': 'error', 'error': str(e)}

    def ingest_all_modalities(self) -> Dict[str, Any]:
        """Ingest all data modalities with comprehensive validation"""
        logger.info("Starting complete multimodal data ingestion")

        results = {
            'healthcare': self.ingest_healthcare_csv(),
            'barcodes': self.ingest_barcode_images(),
            'video_frames': self.ingest_video_frames(),
            'mhealth': self.ingest_mhealth_telemetry()
        }

        # Compute overall ingestion status
        success_count = sum(1 for r in results.values() if r['status'] == 'success')
        overall_status = ('success' if success_count == len(results) else
                          'partial_success' if success_count else 'failed')

        summary = {
            'overall_status': overall_status,
            'successful_modalities': success_count,
            'total_modalities': len(results),
            'ingestion_timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'results': results
        }

        self._stage_json("ingestion_summary.json", summarize(summary))

        logger.info(f"Multimodal ingestion completed: {success_count}/{len(results)} modalities successful")
        return summary


def summarize(ingestion: Dict[str, Any]) -> Dict[str, Any]:
    """The ingestion results without the data itself (for staging and reports)."""
    summary = {k: v for k, v in ingestion.items() if k != 'results'}
    summary['results'] = {modality: {k: v for k, v in result.items() if k != 'data'}
                          for modality, result in ingestion['results'].items()}
    return summary


if __name__ == "__main__":
    # Test ingestion module
    logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')
    arch = PipelineArchitecture(REPO_ROOT)
    ingestion = DataIngestionModule(arch)

    results = ingestion.ingest_all_modalities()
    print(f"Ingestion test completed: {results['overall_status']}")
