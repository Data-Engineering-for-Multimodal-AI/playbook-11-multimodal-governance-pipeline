"""
Inference Module for Medical Cart Pipeline

Implements:
- Prescription-to-barcode matching
- Navigation analysis from video frames
- Telemetry analysis for cart stability
- Robustness checks under various conditions
"""

import os
import cv2
import pandas as pd
import numpy as np
import json
import uuid
import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
import logging
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.feature_extraction.text import TfidfVectorizer
import hashlib

from pipeline_architecture import PipelineArchitecture, LineageEvent, ProcessingStage, DataModality

logger = logging.getLogger(__name__)

class PrescriptionMatcher:
    """Matches prescriptions from healthcare data against barcode scans"""
    
    def __init__(self):
        self.medication_barcode_map = {
            # Simulated medication-to-barcode mapping
            'Paracetamol': 'code128',
            'Ibuprofen': 'code39',
            'Aspirin': 'ean13',
            'Insulin': 'qrcode',
            'Metformin': 'datamatrix',
            'Lisinopril': 'itf'
        }
        
        self.vectorizer = TfidfVectorizer(stop_words='english', lowercase=True)
    
    def extract_medication_list(self, healthcare_df: pd.DataFrame) -> List[Dict[str, Any]]:
        """Extract unique medications from healthcare data"""
        medications = []
        
        if 'Medication' in healthcare_df.columns:
            unique_meds = healthcare_df['Medication'].unique()
            
            for med in unique_meds:
                if pd.notna(med):
                    medications.append({
                        'medication_name': med,
                        'prescription_count': (healthcare_df['Medication'] == med).sum(),
                        'expected_barcode': self.medication_barcode_map.get(med, 'unknown')
                    })
        
        return medications
    
    def simulate_barcode_scan(self, barcode_type: str) -> Dict[str, Any]:
        """Simulate barcode scanning results"""
        # In real implementation, this would use actual barcode scanning
        scan_results = {
            'code128': {'data': 'PARACETAMOL_500MG_LOT123', 'confidence': 0.95},
            'code39': {'data': 'IBUPROFEN_200MG_LOT456', 'confidence': 0.92},
            'ean13': {'data': '1234567890123', 'confidence': 0.98},  # Aspirin
            'qrcode': {'data': 'INSULIN_100UNITS_LOT789', 'confidence': 0.99},
            'datamatrix': {'data': 'METFORMIN_850MG_LOT321', 'confidence': 0.89},
            'itf': {'data': 'LISINOPRIL_10MG_LOT654', 'confidence': 0.91}
        }
        
        return scan_results.get(barcode_type, {'data': 'UNKNOWN', 'confidence': 0.0})
    
    def match_prescription_to_barcode(self, prescription: str, barcode_data: str) -> Dict[str, Any]:
        """Match prescription against barcode data using text similarity"""
        
        # Extract medication name from prescription
        prescription_clean = prescription.upper().replace(' ', '')
        barcode_clean = barcode_data.upper().replace('_', ' ')
        
        # Simple substring matching
        direct_match = prescription_clean in barcode_clean
        
        # Text similarity matching
        try:
            tfidf_matrix = self.vectorizer.fit_transform([prescription, barcode_data])
            similarity_score = cosine_similarity(tfidf_matrix[0:1], tfidf_matrix[1:2])[0][0]
        except:
            similarity_score = 0.0
        
        match_confidence = similarity_score if direct_match else similarity_score * 0.5
        
        return {
            'direct_match': direct_match,
            'similarity_score': similarity_score,
            'match_confidence': match_confidence,
            'match_status': 'confirmed' if match_confidence > 0.7 else 'uncertain' if match_confidence > 0.3 else 'no_match'
        }
    
    def process_prescription_matching(self, healthcare_df: pd.DataFrame, barcode_metadata: Dict[str, Any]) -> Dict[str, Any]:
        """Process complete prescription-to-barcode matching"""
        
        medications = self.extract_medication_list(healthcare_df)
        matching_results = []
        
        for med_info in medications:
            medication = med_info['medication_name']
            expected_barcode = med_info['expected_barcode']
            
            if expected_barcode != 'unknown' and expected_barcode in barcode_metadata:
                # Simulate barcode scan
                scan_result = self.simulate_barcode_scan(expected_barcode)
                
                # Perform matching
                match_result = self.match_prescription_to_barcode(medication, scan_result['data'])
                
                matching_results.append({
                    'medication': medication,
                    'prescription_count': med_info['prescription_count'],
                    'expected_barcode_type': expected_barcode,
                    'scanned_data': scan_result['data'],
                    'scan_confidence': scan_result['confidence'],
                    'match_result': match_result,
                    'overall_confidence': match_result['match_confidence'] * scan_result['confidence']
                })
        
        # Calculate summary statistics
        total_matches = len(matching_results)
        confirmed_matches = sum(1 for r in matching_results if r['match_result']['match_status'] == 'confirmed')
        uncertain_matches = sum(1 for r in matching_results if r['match_result']['match_status'] == 'uncertain')
        
        return {
            'matching_results': matching_results,
            'summary': {
                'total_medications': total_matches,
                'confirmed_matches': confirmed_matches,
                'uncertain_matches': uncertain_matches,
                'no_matches': total_matches - confirmed_matches - uncertain_matches,
                'match_success_rate': confirmed_matches / total_matches if total_matches > 0 else 0
            }
        }

class NavigationAnalyzer:
    """Analyzes video frames for corridor navigation and obstacle detection"""
    
    def __init__(self):
        self.corridor_features = []
    
    def detect_corridor_features(self, frame: np.ndarray) -> Dict[str, Any]:
        """Detect corridor features from video frame"""
        
        # Convert to grayscale for processing
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        
        # Edge detection for walls and obstacles
        edges = cv2.Canny(gray, 50, 150)
        
        # Line detection for corridor walls
        lines = cv2.HoughLinesP(edges, 1, np.pi/180, threshold=50, minLineLength=50, maxLineGap=10)
        
        # Detect corners/turns
        corners = cv2.goodFeaturesToTrack(gray, maxCorners=100, qualityLevel=0.01, minDistance=10)
        
        # Calculate corridor width estimation
        height, width = gray.shape
        wall_lines = []
        
        if lines is not None:
            for line in lines:
                x1, y1, x2, y2 = line[0]
                # Filter for vertical lines (walls)
                if abs(x2 - x1) < 20:  # Nearly vertical
                    wall_lines.append(line[0])
        
        # Estimate corridor width
        corridor_width = width  # Default to full frame width
        if len(wall_lines) >= 2:
            left_walls = [line for line in wall_lines if line[0] < width/2]
            right_walls = [line for line in wall_lines if line[0] > width/2]
            
            if left_walls and right_walls:
                leftmost = max([line[0] for line in left_walls])
                rightmost = min([line[0] for line in right_walls])
                corridor_width = rightmost - leftmost
        
        return {
            'frame_dimensions': (height, width),
            'edge_pixels': np.sum(edges > 0),
            'detected_lines': len(lines) if lines is not None else 0,
            'detected_corners': len(corners) if corners is not None else 0,
            'estimated_corridor_width': corridor_width,
            'corridor_width_ratio': corridor_width / width,
            'navigation_complexity': np.sum(edges > 0) / (height * width)  # Edge density
        }
    
    def analyze_occlusion_robustness(self, frame: np.ndarray, occlusion_level: float = 0.3) -> Dict[str, Any]:
        """Test navigation robustness under partial occlusion"""
        
        height, width = frame.shape[:2]
        
        # Create occluded versions of the frame
        occluded_frames = []
        
        # Central occlusion (simulating obstacle)
        central_occluded = frame.copy()
        occlusion_size = int(min(height, width) * occlusion_level)
        center_y, center_x = height // 2, width // 2
        central_occluded[center_y-occlusion_size//2:center_y+occlusion_size//2,
                        center_x-occlusion_size//2:center_x+occlusion_size//2] = 0
        
        # Side occlusion (simulating partial view blockage)
        side_occluded = frame.copy()
        side_occluded[:, :int(width * occlusion_level)] = 0
        
        # Analyze each occluded frame
        original_features = self.detect_corridor_features(frame)
        central_features = self.detect_corridor_features(central_occluded)
        side_features = self.detect_corridor_features(side_occluded)
        
        # Calculate robustness metrics
        def calculate_feature_retention(original, occluded):
            line_retention = occluded['detected_lines'] / max(original['detected_lines'], 1)
            corner_retention = occluded['detected_corners'] / max(original['detected_corners'], 1)
            width_retention = abs(occluded['estimated_corridor_width'] - original['estimated_corridor_width']) / max(original['estimated_corridor_width'], 1)
            return (line_retention + corner_retention + (1 - width_retention)) / 3
        
        central_robustness = calculate_feature_retention(original_features, central_features)
        side_robustness = calculate_feature_retention(original_features, side_features)
        
        return {
            'original_features': original_features,
            'occlusion_level': occlusion_level,
            'central_occlusion_robustness': central_robustness,
            'side_occlusion_robustness': side_robustness,
            'average_robustness': (central_robustness + side_robustness) / 2,
            'robustness_status': 'good' if (central_robustness + side_robustness) / 2 > 0.7 else 'adequate' if (central_robustness + side_robustness) / 2 > 0.4 else 'poor'
        }
    
    def process_navigation_analysis(self, frames_metadata: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Process navigation analysis for all video frames"""
        
        navigation_results = []
        robustness_results = []
        
        for frame_info in frames_metadata[:10]:  # Process first 10 frames for demo
            frame_path = Path(frame_info['file_path'])
            
            if frame_path.exists():
                frame = cv2.imread(str(frame_path))
                
                if frame is not None:
                    # Basic navigation analysis
                    nav_features = self.detect_corridor_features(frame)
                    nav_features['frame_number'] = frame_info['frame_number']
                    nav_features['timestamp'] = frame_info['timestamp']
                    navigation_results.append(nav_features)
                    
                    # Robustness analysis
                    robustness = self.analyze_occlusion_robustness(frame)
                    robustness['frame_number'] = frame_info['frame_number']
                    robustness_results.append(robustness)
        
        # Calculate summary statistics
        if navigation_results:
            avg_complexity = np.mean([r['navigation_complexity'] for r in navigation_results])
            avg_corridor_width = np.mean([r['estimated_corridor_width'] for r in navigation_results])
            avg_robustness = np.mean([r['average_robustness'] for r in robustness_results])
        else:
            avg_complexity = 0
            avg_corridor_width = 0
            avg_robustness = 0
        
        return {
            'navigation_analysis': navigation_results,
            'robustness_analysis': robustness_results,
            'summary': {
                'frames_processed': len(navigation_results),
                'average_navigation_complexity': avg_complexity,
                'average_corridor_width': avg_corridor_width,
                'average_occlusion_robustness': avg_robustness,
                'navigation_status': 'good' if avg_robustness > 0.7 and avg_complexity < 0.3 else 'adequate' if avg_robustness > 0.4 else 'poor'
            }
        }

class TelemetryAnalyzer:
    """Analyzes MHealth telemetry data for cart stability and anomaly detection"""
    
    def __init__(self):
        self.stability_thresholds = {
            'acceleration_variance': 2.0,
            'gyro_variance': 1.5,
            'acceleration_magnitude': 15.0
        }
    
    def analyze_stability_metrics(self, telemetry_data: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze cart stability from telemetry sensor data"""
        
        stability_results = {}
        
        for subject_id, subject_data in telemetry_data.items():
            if 'data_sample' in subject_data:
                sample_data = pd.DataFrame(subject_data['data_sample'])
                
                # Extract accelerometer data (simulating cart movement)
                accel_cols = [col for col in sample_data.columns if 'acc' in col.lower()]
                gyro_cols = [col for col in sample_data.columns if 'gyro' in col.lower()]
                
                if accel_cols and gyro_cols:
                    # Calculate stability metrics
                    accel_data = sample_data[accel_cols].dropna()
                    gyro_data = sample_data[gyro_cols].dropna()
                    
                    # Acceleration magnitude
                    accel_magnitude = np.sqrt(np.sum(accel_data**2, axis=1))
                    
                    # Variance metrics
                    accel_variance = np.var(accel_magnitude)
                    gyro_variance = np.mean([np.var(gyro_data[col]) for col in gyro_cols])
                    
                    # Stability indicators
                    excessive_acceleration = np.sum(accel_magnitude > self.stability_thresholds['acceleration_magnitude'])
                    high_variance_periods = accel_variance > self.stability_thresholds['acceleration_variance']
                    
                    # Missing data detection
                    missing_data_ratio = sample_data.isnull().sum().sum() / (len(sample_data) * len(sample_data.columns))
                    
                    stability_results[subject_id] = {
                        'acceleration_variance': accel_variance,
                        'gyro_variance': gyro_variance,
                        'max_acceleration': np.max(accel_magnitude),
                        'mean_acceleration': np.mean(accel_magnitude),
                        'excessive_acceleration_events': excessive_acceleration,
                        'high_variance_detected': high_variance_periods,
                        'missing_data_ratio': missing_data_ratio,
                        'stability_score': max(0, 1 - (accel_variance / 10 + gyro_variance / 10 + missing_data_ratio)),
                        'stability_status': 'stable' if accel_variance < 2.0 and gyro_variance < 1.5 else 'unstable'
                    }
        
        # Overall stability assessment
        if stability_results:
            avg_stability_score = np.mean([r['stability_score'] for r in stability_results.values()])
            stable_subjects = sum(1 for r in stability_results.values() if r['stability_status'] == 'stable')
            
            overall_status = 'stable' if avg_stability_score > 0.7 else 'moderately_stable' if avg_stability_score > 0.4 else 'unstable'
        else:
            avg_stability_score = 0
            stable_subjects = 0
            overall_status = 'unknown'
        
        return {
            'subject_stability': stability_results,
            'summary': {
                'subjects_analyzed': len(stability_results),
                'stable_subjects': stable_subjects,
                'average_stability_score': avg_stability_score,
                'overall_stability_status': overall_status
            }
        }

class InferenceModule:
    """Main inference module coordinator"""
    
    def __init__(self, architecture: PipelineArchitecture):
        self.arch = architecture
        self.prescription_matcher = PrescriptionMatcher()
        self.navigation_analyzer = NavigationAnalyzer()
        self.telemetry_analyzer = TelemetryAnalyzer()
    
    def run_complete_inference(self, ingestion_results: Dict[str, Any]) -> Dict[str, Any]:
        """Run complete inference pipeline on all modalities"""
        logger.info("Starting complete inference analysis")
        
        inference_results = {
            'prescription_matching': None,
            'navigation_analysis': None,
            'telemetry_analysis': None,
            'cross_modal_insights': {}
        }
        
        # Prescription matching
        if (ingestion_results['healthcare']['status'] == 'success' and 
            ingestion_results['barcodes']['status'] == 'success'):
            
            healthcare_df = ingestion_results['healthcare']['data']
            barcode_metadata = ingestion_results['barcodes']['data']
            
            prescription_results = self.prescription_matcher.process_prescription_matching(
                healthcare_df, barcode_metadata
            )
            inference_results['prescription_matching'] = prescription_results
            
            # Record lineage
            event = LineageEvent(
                event_id=str(uuid.uuid4()),
                timestamp=datetime.datetime.now().isoformat(),
                stage=ProcessingStage.INFERENCE,
                modality=DataModality.HEALTHCARE_CSV,
                data_hash=hashlib.sha256(str(prescription_results).encode()).hexdigest(),
                previous_hash="",
                metadata={'inference_type': 'prescription_matching', 'results_summary': prescription_results['summary']}
            )
            self.arch.record_lineage_event(event)
        
        # Navigation analysis
        if ingestion_results['video_frames']['status'] == 'success':
            frames_metadata = ingestion_results['video_frames']['data']
            
            navigation_results = self.navigation_analyzer.process_navigation_analysis(frames_metadata)
            inference_results['navigation_analysis'] = navigation_results
            
            # Record lineage
            event = LineageEvent(
                event_id=str(uuid.uuid4()),
                timestamp=datetime.datetime.now().isoformat(),
                stage=ProcessingStage.INFERENCE,
                modality=DataModality.VIDEO_FRAME,
                data_hash=hashlib.sha256(str(navigation_results).encode()).hexdigest(),
                previous_hash="",
                metadata={'inference_type': 'navigation_analysis', 'results_summary': navigation_results['summary']}
            )
            self.arch.record_lineage_event(event)
        
        # Telemetry analysis
        if ingestion_results['mhealth']['status'] == 'success':
            telemetry_data = ingestion_results['mhealth']['data']
            
            telemetry_results = self.telemetry_analyzer.analyze_stability_metrics(telemetry_data)
            inference_results['telemetry_analysis'] = telemetry_results
            
            # Record lineage
            event = LineageEvent(
                event_id=str(uuid.uuid4()),
                timestamp=datetime.datetime.now().isoformat(),
                stage=ProcessingStage.INFERENCE,
                modality=DataModality.MHEALTH_TELEMETRY,
                data_hash=hashlib.sha256(str(telemetry_results).encode()).hexdigest(),
                previous_hash="",
                metadata={'inference_type': 'telemetry_analysis', 'results_summary': telemetry_results['summary']}
            )
            self.arch.record_lineage_event(event)
        
        # Cross-modal insights
        inference_results['cross_modal_insights'] = self._generate_cross_modal_insights(inference_results)
        
        logger.info("Complete inference analysis completed")
        return inference_results
    
    def _generate_cross_modal_insights(self, results: Dict[str, Any]) -> Dict[str, Any]:
        """Generate insights from cross-modal analysis"""
        
        insights = {
            'delivery_success_prediction': 'unknown',
            'risk_factors': [],
            'recommendations': []
        }
        
        # Analyze prescription matching success
        if results['prescription_matching']:
            match_rate = results['prescription_matching']['summary']['match_success_rate']
            if match_rate < 0.8:
                insights['risk_factors'].append('Low prescription-barcode match rate')
                insights['recommendations'].append('Improve barcode scanning accuracy')
        
        # Analyze navigation capabilities
        if results['navigation_analysis']:
            nav_status = results['navigation_analysis']['summary']['navigation_status']
            if nav_status == 'poor':
                insights['risk_factors'].append('Poor navigation robustness')
                insights['recommendations'].append('Enhance obstacle detection algorithms')
        
        # Analyze cart stability
        if results['telemetry_analysis']:
            stability_status = results['telemetry_analysis']['summary']['overall_stability_status']
            if stability_status == 'unstable':
                insights['risk_factors'].append('Cart stability issues detected')
                insights['recommendations'].append('Check mechanical components and sensors')
        
        # Overall delivery prediction
        if len(insights['risk_factors']) == 0:
            insights['delivery_success_prediction'] = 'high'
        elif len(insights['risk_factors']) <= 1:
            insights['delivery_success_prediction'] = 'medium'
        else:
            insights['delivery_success_prediction'] = 'low'
        
        return insights

if __name__ == "__main__":
    # Test inference module
    arch = PipelineArchitecture("/Users/vasundras/Desktop/pb-11-mmgovernancepipeline")
    inference = InferenceModule(arch)
    
    print("Inference module test completed")