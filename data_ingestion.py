"""
Data Ingestion Module for Multimodal Medical Cart Pipeline

Handles loading and validation of all data modalities:
- Healthcare CSV (EHR-like records)
- Barcode images (various formats)
- Video frames (corridor navigation)
- MHealth telemetry (sensor data)
"""

import os
import cv2
import pandas as pd
import numpy as np
from PIL import Image
import json
import hashlib
import uuid
import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
import logging

from pipeline_architecture import PipelineArchitecture, LineageEvent, ProcessingStage, DataModality

logger = logging.getLogger(__name__)

class DataIngestionModule:
    """Handles ingestion of multimodal data with validation and staging"""
    
    def __init__(self, architecture: PipelineArchitecture):
        self.arch = architecture
        self.staging_path = architecture.staged_path
        
    def compute_data_hash(self, data: Any) -> str:
        """Compute hash for data integrity verification"""
        if isinstance(data, pd.DataFrame):
            return hashlib.sha256(str(data.values.tobytes()).encode()).hexdigest()
        elif isinstance(data, np.ndarray):
            return hashlib.sha256(data.tobytes()).hexdigest()
        elif isinstance(data, (str, bytes)):
            return hashlib.sha256(str(data).encode()).hexdigest()
        else:
            return hashlib.sha256(str(data).encode()).hexdigest()
    
    def ingest_healthcare_csv(self) -> Dict[str, Any]:
        """Ingest and validate healthcare CSV data"""
        logger.info("Starting healthcare CSV ingestion")
        
        csv_path = self.arch.data_path / "healthcare_dataset.csv"
        
        try:
            # Load CSV with validation
            df = pd.read_csv(csv_path)
            
            # Basic validation
            required_columns = ['Name', 'Age', 'Medical Condition', 'Medication']
            missing_cols = [col for col in required_columns if col not in df.columns]
            
            if missing_cols:
                raise ValueError(f"Missing required columns: {missing_cols}")
            
            # Data quality checks
            validation_results = {
                'total_records': len(df),
                'missing_names': df['Name'].isna().sum(),
                'invalid_ages': (df['Age'] < 0).sum() if 'Age' in df.columns else 0,
                'missing_medications': df['Medication'].isna().sum(),
                'phi_fields_detected': ['Name', 'Age', 'Medical Condition']
            }
            
            # Stage cleaned data
            staged_file = self.staging_path / "healthcare_staged.csv"
            df.to_csv(staged_file, index=False)
            
            # Convert numpy types to Python types for JSON serialization
            validation_results_json = {
                'total_records': int(validation_results['total_records']),
                'missing_names': int(validation_results['missing_names']),
                'invalid_ages': int(validation_results['invalid_ages']),
                'missing_medications': int(validation_results['missing_medications']),
                'phi_fields_detected': validation_results['phi_fields_detected']
            }
            
            # Record lineage event
            data_hash = self.compute_data_hash(df)
            event = LineageEvent(
                event_id=str(uuid.uuid4()),
                timestamp=datetime.datetime.now().isoformat(),
                stage=ProcessingStage.INGESTION,
                modality=DataModality.HEALTHCARE_CSV,
                data_hash=data_hash,
                previous_hash="",
                metadata={
                    'source_file': str(csv_path),
                    'staged_file': str(staged_file),
                    'validation_results': validation_results_json
                }
            )
            
            self.arch.record_lineage_event(event)
            
            logger.info(f"Healthcare CSV ingestion completed: {len(df)} records")
            return {
                'status': 'success',
                'data': df,
                'validation': validation_results_json,
                'staged_file': str(staged_file)
            }
            
        except Exception as e:
            logger.error(f"Healthcare CSV ingestion failed: {str(e)}")
            return {'status': 'error', 'error': str(e)}
    
    def ingest_barcode_images(self) -> Dict[str, Any]:
        """Ingest and validate barcode images"""
        logger.info("Starting barcode image ingestion")
        
        barcode_path = self.arch.data_path / "bar-codes"
        
        try:
            barcode_data = {}
            validation_results = {
                'total_images': 0,
                'valid_images': 0,
                'invalid_images': 0,
                'formats_detected': []
            }
            
            for image_file in barcode_path.glob("*.png"):
                try:
                    # Load and validate image
                    img = cv2.imread(str(image_file))
                    if img is None:
                        validation_results['invalid_images'] += 1
                        continue
                    
                    # Extract barcode type from filename
                    barcode_type = image_file.stem.replace('-1', '')
                    
                    # Store image metadata
                    barcode_data[barcode_type] = {
                        'file_path': str(image_file),
                        'shape': img.shape,
                        'type': barcode_type,
                        'size_bytes': image_file.stat().st_size
                    }
                    
                    validation_results['valid_images'] += 1
                    validation_results['formats_detected'].append(barcode_type)
                    
                except Exception as e:
                    logger.warning(f"Failed to load barcode image {image_file}: {str(e)}")
                    validation_results['invalid_images'] += 1
                
                validation_results['total_images'] += 1
            
            # Stage barcode metadata
            staged_file = self.staging_path / "barcode_metadata.json"
            with open(staged_file, 'w') as f:
                json.dump(barcode_data, f, indent=2)
            
            # Record lineage event
            data_hash = self.compute_data_hash(json.dumps(barcode_data, sort_keys=True))
            event = LineageEvent(
                event_id=str(uuid.uuid4()),
                timestamp=datetime.datetime.now().isoformat(),
                stage=ProcessingStage.INGESTION,
                modality=DataModality.BARCODE_IMAGE,
                data_hash=data_hash,
                previous_hash="",
                metadata={
                    'source_path': str(barcode_path),
                    'staged_file': str(staged_file),
                    'validation_results': validation_results
                }
            )
            
            self.arch.record_lineage_event(event)
            
            logger.info(f"Barcode ingestion completed: {validation_results['valid_images']} valid images")
            return {
                'status': 'success',
                'data': barcode_data,
                'validation': validation_results,
                'staged_file': str(staged_file)
            }
            
        except Exception as e:
            logger.error(f"Barcode ingestion failed: {str(e)}")
            return {'status': 'error', 'error': str(e)}
    
    def ingest_video_frames(self, max_frames: int = 100) -> Dict[str, Any]:
        """Extract and ingest video frames for navigation analysis"""
        logger.info("Starting video frame ingestion")
        
        video_path = self.arch.data_path / "samples_data_vtest.avi"
        
        try:
            cap = cv2.VideoCapture(str(video_path))
            if not cap.isOpened():
                raise ValueError(f"Cannot open video file: {video_path}")
            
            frames_data = []
            frame_count = 0
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            fps = cap.get(cv2.CAP_PROP_FPS)
            
            # Extract frames at regular intervals
            frame_interval = max(1, total_frames // max_frames)
            
            while frame_count < total_frames and len(frames_data) < max_frames:
                cap.set(cv2.CAP_PROP_POS_FRAMES, frame_count)
                ret, frame = cap.read()
                
                if not ret:
                    break
                
                # Save frame
                frame_filename = f"frame_{frame_count:06d}.png"
                frame_path = self.staging_path / frame_filename
                cv2.imwrite(str(frame_path), frame)
                
                # Store frame metadata
                frames_data.append({
                    'frame_number': frame_count,
                    'timestamp': frame_count / fps,
                    'file_path': str(frame_path),
                    'shape': frame.shape,
                    'hash': self.compute_data_hash(frame)
                })
                
                frame_count += frame_interval
            
            cap.release()
            
            # Stage frame metadata
            staged_file = self.staging_path / "video_frames_metadata.json"
            with open(staged_file, 'w') as f:
                json.dump(frames_data, f, indent=2)
            
            validation_results = {
                'total_frames_in_video': total_frames,
                'frames_extracted': len(frames_data),
                'fps': fps,
                'duration_seconds': total_frames / fps,
                'extraction_interval': frame_interval
            }
            
            # Record lineage event
            data_hash = self.compute_data_hash(json.dumps(frames_data, sort_keys=True))
            event = LineageEvent(
                event_id=str(uuid.uuid4()),
                timestamp=datetime.datetime.now().isoformat(),
                stage=ProcessingStage.INGESTION,
                modality=DataModality.VIDEO_FRAME,
                data_hash=data_hash,
                previous_hash="",
                metadata={
                    'source_file': str(video_path),
                    'staged_file': str(staged_file),
                    'validation_results': validation_results
                }
            )
            
            self.arch.record_lineage_event(event)
            
            logger.info(f"Video frame ingestion completed: {len(frames_data)} frames extracted")
            return {
                'status': 'success',
                'data': frames_data,
                'validation': validation_results,
                'staged_file': str(staged_file)
            }
            
        except Exception as e:
            logger.error(f"Video frame ingestion failed: {str(e)}")
            return {'status': 'error', 'error': str(e)}
    
    def ingest_mhealth_telemetry(self, sample_subjects: int = 3) -> Dict[str, Any]:
        """Ingest MHealth telemetry data for cart stability analysis"""
        logger.info("Starting MHealth telemetry ingestion")
        
        mhealth_path = self.arch.data_path / "MHEALTHDATASET"
        
        try:
            telemetry_data = {}
            validation_results = {
                'total_subjects': 0,
                'valid_subjects': 0,
                'invalid_subjects': 0,
                'total_samples': 0,
                'columns_per_subject': {}
            }
            
            # Process sample subjects
            subject_files = list(mhealth_path.glob("mHealth_subject*.log"))[:sample_subjects]
            
            for subject_file in subject_files:
                try:
                    # Load telemetry data (space-separated values)
                    df = pd.read_csv(subject_file, delimiter='\t', header=None)
                    
                    # Apply column names from README
                    column_names = [
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
                    
                    if len(df.columns) == len(column_names):
                        df.columns = column_names
                    
                    subject_id = subject_file.stem.replace('mHealth_subject', '')
                    
                    # Sample data for performance (take every 10th sample)
                    df_sampled = df.iloc[::10].copy()
                    
                    telemetry_data[subject_id] = {
                        'subject_id': subject_id,
                        'total_samples': len(df),
                        'sampled_samples': len(df_sampled),
                        'columns': list(df.columns),
                        'activities': df['activity_label'].unique().tolist() if 'activity_label' in df.columns else [],
                        'data_sample': df_sampled.head(100).to_dict('records')  # Store small sample
                    }
                    
                    validation_results['valid_subjects'] += 1
                    validation_results['total_samples'] += len(df)
                    validation_results['columns_per_subject'][subject_id] = len(df.columns)
                    
                except Exception as e:
                    logger.warning(f"Failed to load telemetry data {subject_file}: {str(e)}")
                    validation_results['invalid_subjects'] += 1
                
                validation_results['total_subjects'] += 1
            
            # Stage telemetry metadata
            staged_file = self.staging_path / "mhealth_telemetry.json"
            with open(staged_file, 'w') as f:
                json.dump(telemetry_data, f, indent=2)
            
            # Record lineage event
            data_hash = self.compute_data_hash(json.dumps(telemetry_data, sort_keys=True))
            event = LineageEvent(
                event_id=str(uuid.uuid4()),
                timestamp=datetime.datetime.now().isoformat(),
                stage=ProcessingStage.INGESTION,
                modality=DataModality.MHEALTH_TELEMETRY,
                data_hash=data_hash,
                previous_hash="",
                metadata={
                    'source_path': str(mhealth_path),
                    'staged_file': str(staged_file),
                    'validation_results': validation_results
                }
            )
            
            self.arch.record_lineage_event(event)
            
            logger.info(f"MHealth telemetry ingestion completed: {validation_results['valid_subjects']} subjects")
            return {
                'status': 'success',
                'data': telemetry_data,
                'validation': validation_results,
                'staged_file': str(staged_file)
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
        overall_status = 'success' if success_count == len(results) else 'partial_success'
        
        summary = {
            'overall_status': overall_status,
            'successful_modalities': success_count,
            'total_modalities': len(results),
            'ingestion_timestamp': datetime.datetime.now().isoformat(),
            'results': results
        }
        
        # Save ingestion summary (without DataFrames)
        summary_serializable = {}
        for key, value in summary.items():
            if key == 'results':
                summary_serializable[key] = {}
                for result_key, result_value in value.items():
                    if isinstance(result_value, dict):
                        result_copy = {k: v for k, v in result_value.items() if not isinstance(v, pd.DataFrame)}
                        if 'data' in result_value and isinstance(result_value['data'], pd.DataFrame):
                            df = result_value['data']
                            result_copy['data_summary'] = {
                                'type': 'DataFrame',
                                'shape': list(df.shape),
                                'columns': list(df.columns)
                            }
                        summary_serializable[key][result_key] = result_copy
                    else:
                        summary_serializable[key][result_key] = result_value
            else:
                summary_serializable[key] = value
        
        summary_file = self.staging_path / "ingestion_summary.json"
        with open(summary_file, 'w') as f:
            json.dump(summary_serializable, f, indent=2, default=str)
        
        logger.info(f"Multimodal ingestion completed: {success_count}/{len(results)} modalities successful")
        return summary

if __name__ == "__main__":
    # Test ingestion module
    arch = PipelineArchitecture("/Users/vasundras/Desktop/pb-11-mmgovernancepipeline")
    ingestion = DataIngestionModule(arch)
    
    results = ingestion.ingest_all_modalities()
    print(f"Ingestion test completed: {results['overall_status']}")