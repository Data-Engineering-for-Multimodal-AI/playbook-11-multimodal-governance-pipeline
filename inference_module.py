"""
Inference Module for Medical Cart Pipeline

Implements:
- Prescription-to-barcode matching: decoded labels checked against the pharmacy formulary
- Navigation analysis: people in the cart's path (OpenCV HOG person detector) -> yield or proceed
- Telemetry analysis: a motion/stillness monitor on the MHEALTH chest accelerometer, scored
  against the dataset's activity labels on subjects it was not fitted on
- Robustness checks under various conditions (blur, rotation, occlusion, noise, low light)
"""

import json
import hashlib
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

import cv2
import numpy as np
import pandas as pd
import zxingcpp

from pipeline_architecture import PipelineArchitecture, ProcessingStage, DataModality, new_event
from security_module import pixelate

logger = logging.getLogger(__name__)

FORMULARY_FILE = "formulary.csv"

MHEALTH_ACTIVITIES = {
    1: 'Standing still', 2: 'Sitting and relaxing', 3: 'Lying down', 4: 'Walking',
    5: 'Climbing stairs', 6: 'Waist bends forward', 7: 'Frontal elevation of arms',
    8: 'Knees bending (crouching)', 9: 'Cycling', 10: 'Jogging', 11: 'Running', 12: 'Jump front & back'
}
STILL_ACTIVITIES = {1, 2, 3}


def gs1_check_digit_ok(digits: str) -> bool:
    """GS1 mod-10 check digit (EAN-13, UPC-A, ITF-14)"""
    if not digits.isdigit() or len(digits) < 8:
        return False
    body = [int(d) for d in digits[:-1]][::-1]
    total = sum(d * (3 if i % 2 == 0 else 1) for i, d in enumerate(body))
    return (10 - total % 10) % 10 == int(digits[-1])


def _rotate(img: np.ndarray, angle: float) -> np.ndarray:
    h, w = img.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    cos, sin = abs(m[0, 0]), abs(m[0, 1])
    nw, nh = int(h * sin + w * cos), int(h * cos + w * sin)
    m[0, 2] += nw / 2 - w / 2
    m[1, 2] += nh / 2 - h / 2
    return cv2.warpAffine(img, m, (nw, nh), borderValue=(255, 255, 255))


def _strip(img: np.ndarray, fraction: float) -> np.ndarray:
    out = img.copy()
    w = out.shape[1]
    x = int(w * (0.5 - fraction / 2))
    out[:, x:x + int(w * fraction)] = 255
    return out


def _noise(img: np.ndarray, sigma: float) -> np.ndarray:
    rng = np.random.default_rng(0)
    return np.clip(img.astype(np.float32) + rng.normal(0, sigma, img.shape), 0, 255).astype(np.uint8)


# Label conditions a cart's scanner meets: (name, transform)
BARCODE_CONDITIONS = [
    ('blur σ=1', lambda i: cv2.GaussianBlur(i, (0, 0), 1)),
    ('blur σ=2', lambda i: cv2.GaussianBlur(i, (0, 0), 2)),
    ('blur σ=3', lambda i: cv2.GaussianBlur(i, (0, 0), 3)),
    ('rotated 10°', lambda i: _rotate(i, 10)),
    ('rotated 30°', lambda i: _rotate(i, 30)),
    ('rotated 90°', lambda i: _rotate(i, 90)),
    ('5% covered', lambda i: _strip(i, 0.05)),
    ('15% covered', lambda i: _strip(i, 0.15)),
    ('half size', lambda i: cv2.resize(i, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)),
    ('quarter size', lambda i: cv2.resize(i, None, fx=0.25, fy=0.25, interpolation=cv2.INTER_AREA)),
    ('noise σ=15', lambda i: _noise(i, 15)),
    ('noise σ=40', lambda i: _noise(i, 40)),
    ('low light', lambda i: (i * 0.35).astype(np.uint8)),
]


class PrescriptionMatcher:
    """Matches prescriptions from healthcare data against scanned medication labels"""

    def __init__(self, formulary_path: Path):
        # Which label belongs to which medication (sample-data/formulary.csv)
        self.formulary = pd.read_csv(formulary_path, dtype=str)

    def lookup(self, barcode_format: str, value: str) -> Optional[Dict[str, Any]]:
        rows = self.formulary[(self.formulary['barcode_format'] == barcode_format) &
                              (self.formulary['barcode_value'] == value)]
        return rows.iloc[0].to_dict() if len(rows) else None

    def verify_label(self, label: Dict[str, Any]) -> Dict[str, Any]:
        """Is this scanned label a known medication label?"""
        result = {'file': label['file'], 'format': label.get('format'), 'medication': None}
        if not label.get('decoded'):
            result.update(status='undecodable', reason='no barcode could be read from the image')
        elif label.get('quarantined'):
            result.update(status='quarantined',
                          reason='label carries personal data (' + ', '.join(label['phi_categories']) + ')')
        elif label.get('payload') is None:
            result.update(status='not_screened', reason='payload not available (no access to barcode data)')
        else:
            entry = self.lookup(label['format'], label['payload'])
            gs1 = label['format'] in ('EAN-13', 'UPC-A', 'ITF')
            if entry is None:
                result.update(status='unknown_code', reason='not in the formulary')
            elif gs1 and not gs1_check_digit_ok(label['payload']):
                result.update(status='bad_check_digit', reason='GS1 check digit does not match')
            else:
                result.update(status='verified', medication=entry['medication'], pack=entry.get('pack'),
                              reason='in the formulary' + (', GS1 check digit valid' if gs1 else ''))
        return result

    def extract_medication_list(self, healthcare_df: pd.DataFrame) -> List[Dict[str, Any]]:
        """Extract unique medications from healthcare data"""
        counts = healthcare_df['Medication'].dropna().value_counts()
        return [{'medication_name': med, 'prescription_count': int(n)} for med, n in counts.items()]

    def process_prescription_matching(self, healthcare_df: pd.DataFrame,
                                      labels: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Which prescriptions the cart can confirm by scanning the medication's label"""

        label_results = [self.verify_label(label) for label in labels]
        verified = {r['medication']: r for r in label_results if r['status'] == 'verified'}

        matching_results = []
        for med_info in self.extract_medication_list(healthcare_df):
            medication = med_info['medication_name']
            label = verified.get(medication)
            matching_results.append({
                'medication': medication,
                'prescription_count': med_info['prescription_count'],
                'label_file': label['file'] if label else None,
                'barcode_format': label['format'] if label else None,
                'match_status': 'confirmed' if label else 'no_label',
                'reason': label['reason'] if label else 'no scanned label in the formulary for this medication',
            })

        total_rx = sum(r['prescription_count'] for r in matching_results)
        confirmed_rx = sum(r['prescription_count'] for r in matching_results if r['match_status'] == 'confirmed')
        confirmed = [r for r in matching_results if r['match_status'] == 'confirmed']

        return {
            'label_results': label_results,
            'matching_results': matching_results,
            'auto_verified_medications': sorted(verified),
            'summary': {
                'labels_scanned': len(label_results),
                'labels_verified': len(verified),
                'labels_quarantined': sum(r['status'] == 'quarantined' for r in label_results),
                'total_medications': len(matching_results),
                'confirmed_matches': len(confirmed),
                'no_matches': len(matching_results) - len(confirmed),
                'prescriptions': total_rx,
                'prescriptions_auto_verified': confirmed_rx,
                'match_success_rate': confirmed_rx / total_rx if total_rx else 0.0,
            }
        }

    def barcode_robustness(self, labels: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Decode each label again under each condition; a decode counts only if it reads the same payload"""
        decoded = [l for l in labels if l.get('decoded')]
        per_condition, per_format = {}, {}
        for name, transform in BARCODE_CONDITIONS:
            hits = 0
            for label in decoded:
                results = zxingcpp.read_barcodes(transform(label['image']))
                ok = any(hashlib.sha256(r.text.encode()).hexdigest() == label['payload_sha256'] for r in results)
                hits += ok
                per_format.setdefault(label['format'], []).append(ok)
            per_condition[name] = round(hits / len(decoded), 3) if decoded else 0.0
        return {
            'conditions': per_condition,
            'per_format': {fmt: round(float(np.mean(v)), 3) for fmt, v in sorted(per_format.items())},
            'overall_decode_rate': round(float(np.mean(list(per_condition.values()))), 3) if per_condition else 0.0,
            'labels_tested': len(decoded),
        }


class NavigationAnalyzer:
    """Finds people in the cart's path in camera frames"""

    def __init__(self, min_score: float = 0.5):
        self.hog = cv2.HOGDescriptor()
        self.hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
        self.min_score = min_score
        # The cart's path: the middle 40% of the view, from 35% of the height down to the bottom
        self.path_zone = (0.30, 0.35, 0.70, 1.00)

    def detect_people(self, frame: np.ndarray) -> List[Tuple[int, int, int, int]]:
        boxes, scores = self.hog.detectMultiScale(frame, winStride=(8, 8), padding=(8, 8), scale=1.05)
        scores = np.asarray(scores).ravel()
        return [tuple(int(v) for v in box) for box, s in zip(boxes, scores) if s >= self.min_score]

    def in_path(self, box, shape) -> bool:
        """A person is in the path if their feet (bottom centre of the box) are inside the path zone"""
        h, w = shape[:2]
        x, y, bw, bh = box
        fx, fy = (x + bw / 2) / w, (y + bh) / h
        x0, y0, x1, y1 = self.path_zone
        return x0 <= fx <= x1 and y0 <= fy <= y1

    def decide(self, frame: np.ndarray) -> Dict[str, Any]:
        people = self.detect_people(frame)
        in_path = [b for b in people if self.in_path(b, frame.shape)]
        return {'people': people, 'people_in_path': len(in_path),
                'decision': 'yield' if in_path else 'proceed'}

    def detect_corridor_features(self, frame: np.ndarray) -> Dict[str, Any]:
        """People and the yield/proceed decision for one frame"""
        result = self.decide(frame)
        return {'frame_dimensions': list(frame.shape[:2]), 'people_detected': len(result['people']),
                'people_in_path': result['people_in_path'], 'decision': result['decision']}

    def analyze_occlusion_robustness(self, frame: np.ndarray, baseline: Dict[str, Any],
                                     occlusion_level: float = 0.3) -> Dict[str, Any]:
        """Does the decision hold when part of the view is blocked, blurred or dark?"""
        h, w = frame.shape[:2]
        size = int(min(h, w) * occlusion_level)
        central = frame.copy()
        central[h // 2 - size // 2:h // 2 + size // 2, w // 2 - size // 2:w // 2 + size // 2] = 0
        side = frame.copy()
        side[:, :int(w * occlusion_level)] = 0
        variants = {
            'central_occlusion': central,
            'side_occlusion': side,
            'motion_blur': cv2.blur(frame, (9, 1)),
            'low_light': (frame * 0.35).astype(np.uint8),
        }
        outcome = {}
        for name, variant in variants.items():
            decision = self.decide(variant)['decision']
            outcome[name] = ('same' if decision == baseline['decision'] else
                             'missed_yield' if baseline['decision'] == 'yield' else 'extra_yield')
        return outcome

    def process_navigation_analysis(self, frames_metadata: List[Dict[str, Any]],
                                    stage_dir: Optional[Path] = None, keyframes: int = 4) -> Dict[str, Any]:
        """Decisions for each sampled frame, their robustness, and de-identified keyframes"""

        navigation_results, robustness_results = [], []
        for frame_info in frames_metadata:
            frame = frame_info['frame']
            decision = self.decide(frame)
            navigation_results.append({'frame_number': frame_info['frame_number'],
                                       'timestamp': frame_info['timestamp'],
                                       'people_detected': len(decision['people']),
                                       'people_in_path': decision['people_in_path'],
                                       'decision': decision['decision'],
                                       '_boxes': decision['people']})
            robustness = self.analyze_occlusion_robustness(frame, decision)
            robustness['frame_number'] = frame_info['frame_number']
            robustness_results.append(robustness)

        # Keyframes for review. The whole frame is pixelated: blurring only the detected people
        # would leave everyone the detector missed recognizable.
        staged = []
        if stage_dir is not None:
            stage_dir.mkdir(parents=True, exist_ok=True)
            for result, frame_info in list(zip(navigation_results, frames_metadata))[::max(1, len(frames_metadata) // keyframes)][:keyframes]:
                view = pixelate(frame_info['frame'])
                h, w = view.shape[:2]
                x0, y0, x1, y1 = self.path_zone
                cv2.rectangle(view, (int(x0 * w), int(y0 * h)), (int(x1 * w), int(y1 * h) - 1), (0, 200, 255), 2)
                for (x, y, bw, bh) in result['_boxes']:
                    color = (0, 0, 255) if self.in_path((x, y, bw, bh), view.shape) else (0, 255, 0)
                    cv2.rectangle(view, (x, y), (x + bw, y + bh), color, 2)
                cv2.putText(view, result['decision'].upper(), (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 200, 255), 2)
                path = stage_dir / f"frame_{result['frame_number']:06d}.png"
                cv2.imwrite(str(path), view)
                staged.append(path)
        for result in navigation_results:
            result.pop('_boxes')

        conditions = ['central_occlusion', 'side_occlusion', 'motion_blur', 'low_light']
        n = len(robustness_results)
        per_condition = {c: {'same_decision': sum(r[c] == 'same' for r in robustness_results) / n if n else 0.0,
                             'missed_yields': sum(r[c] == 'missed_yield' for r in robustness_results),
                             'extra_yields': sum(r[c] == 'extra_yield' for r in robustness_results)}
                         for c in conditions}
        avg_robustness = float(np.mean([v['same_decision'] for v in per_condition.values()])) if n else 0.0
        yields = sum(r['decision'] == 'yield' for r in navigation_results)

        return {
            'navigation_analysis': navigation_results,
            'robustness_analysis': robustness_results,
            'staged_keyframes': [str(p) for p in staged],
            'summary': {
                'frames_processed': len(navigation_results),
                'people_detected_per_frame': round(float(np.mean([r['people_detected'] for r in navigation_results])), 2) if n else 0.0,
                'frames_with_people_in_path': yields,
                'yield_rate': yields / n if n else 0.0,
                'robustness_by_condition': per_condition,
                'missed_yields_under_stress': sum(v['missed_yields'] for v in per_condition.values()),
                'average_occlusion_robustness': avg_robustness,
                'navigation_status': ('good' if avg_robustness >= 0.7 else
                                      'adequate' if avg_robustness >= 0.4 else 'poor'),
            }
        }


class TelemetryAnalyzer:
    """A motion/stillness monitor on the chest accelerometer (stand-in for a cart-mounted IMU)

    Each 2-second window (100 samples at 50 Hz) gets one number: the standard deviation of the
    acceleration magnitude. Below a threshold the window is "still". The threshold is fitted on
    subjects 1-5 and scored on subjects 6-10 against the dataset's own activity labels
    (standing, sitting, lying = still; the nine other activities = moving).
    """

    def __init__(self, window: int = 100, train_subjects=('1', '2', '3', '4', '5')):
        self.window = window
        self.train_subjects = set(train_subjects)
        self.stability_thresholds = {}

    def windows(self, df: pd.DataFrame, noise: float = 0.0, dropout: float = 0.0,
                seed: int = 0) -> Tuple[np.ndarray, np.ndarray]:
        """(feature per window, activity per window) for windows with a single activity"""
        acc = df[['chest_acc_x', 'chest_acc_y', 'chest_acc_z']].to_numpy(dtype=float)
        labels = df['activity_label'].to_numpy()
        rng = np.random.default_rng(seed)
        if noise:
            acc = acc + rng.normal(0, noise, acc.shape)
        magnitude = np.linalg.norm(acc, axis=1)
        if dropout:
            magnitude[rng.random(len(magnitude)) < dropout] = np.nan
        n = len(magnitude) // self.window
        magnitude = magnitude[:n * self.window].reshape(n, self.window)
        labels = labels[:n * self.window].reshape(n, self.window)
        single = (labels == labels[:, :1]).all(axis=1) & (labels[:, 0] > 0)
        return np.nanstd(magnitude[single], axis=1), labels[single, 0]

    @staticmethod
    def balanced_accuracy(still_pred: np.ndarray, activity: np.ndarray) -> float:
        still = np.isin(activity, list(STILL_ACTIVITIES))
        return float((still_pred[still].mean() + (~still_pred[~still]).mean()) / 2)

    def fit_threshold(self, features: np.ndarray, activity: np.ndarray) -> float:
        candidates = np.quantile(features, np.linspace(0.01, 0.99, 197))
        scores = [self.balanced_accuracy(features < t, activity) for t in candidates]
        return float(candidates[int(np.argmax(scores))])

    def analyze_stability_metrics(self, telemetry_data: Dict[str, pd.DataFrame]) -> Dict[str, Any]:
        """Fit on the training subjects, score per held-out subject, and under sensor degradation"""

        per_subject = {s: self.windows(df) for s, df in telemetry_data.items()}
        train = [s for s in per_subject if s in self.train_subjects]
        test = [s for s in per_subject if s not in self.train_subjects]
        if not train or not test:
            return {'summary': {'subjects_analyzed': len(per_subject), 'overall_stability_status': 'unknown'},
                    'subject_stability': {}}

        threshold = self.fit_threshold(np.concatenate([per_subject[s][0] for s in train]),
                                       np.concatenate([per_subject[s][1] for s in train]))
        self.stability_thresholds['acceleration_std'] = threshold

        stability_results = {}
        for s in test:
            features, activity = per_subject[s]
            still_pred = features < threshold
            stability_results[s] = {
                'windows': int(len(features)),
                'balanced_accuracy': round(self.balanced_accuracy(still_pred, activity), 4),
                'read_as_still_by_activity': {MHEALTH_ACTIVITIES[a]: round(float(still_pred[activity == a].mean()), 3)
                                              for a in sorted(set(activity.tolist()))},
            }

        test_features = np.concatenate([per_subject[s][0] for s in test])
        test_activity = np.concatenate([per_subject[s][1] for s in test])
        test_ba = self.balanced_accuracy(test_features < threshold, test_activity)

        # Confusions worth explaining: moving activities often read as still, and the reverse
        confusions = []
        for a in sorted(set(test_activity.tolist())):
            rate = float((test_features[test_activity == a] < threshold).mean())
            wrong = rate if a not in STILL_ACTIVITIES else 1 - rate
            if wrong >= 0.05:
                confusions.append({'activity': MHEALTH_ACTIVITIES[a], 'misread_rate': round(wrong, 3),
                                   'misread_as': 'still' if a not in STILL_ACTIVITIES else 'moving'})

        # Sensor degradation: same threshold, degraded signal
        degradation = {}
        for name, kwargs in [('noise σ=0.2 m/s²', {'noise': 0.2}), ('noise σ=0.5 m/s²', {'noise': 0.5}),
                             ('20% samples lost', {'dropout': 0.2}), ('50% samples lost', {'dropout': 0.5})]:
            feats, acts = zip(*(self.windows(telemetry_data[s], **kwargs) for s in test))
            degradation[name] = round(self.balanced_accuracy(np.concatenate(feats) < threshold,
                                                             np.concatenate(acts)), 4)

        accuracies = [r['balanced_accuracy'] for r in stability_results.values()]
        status = ('stable' if test_ba >= 0.9 else 'moderately_stable' if test_ba >= 0.75 else 'unstable')
        return {
            'subject_stability': stability_results,
            'confusions': confusions,
            'degradation': degradation,
            'summary': {
                'subjects_analyzed': len(per_subject),
                'train_subjects': sorted(train, key=int),
                'test_subjects': sorted(test, key=int),
                'threshold_acc_std': round(threshold, 4),
                'test_balanced_accuracy': round(test_ba, 4),
                'worst_subject_accuracy': round(min(accuracies), 4),
                'best_subject_accuracy': round(max(accuracies), 4),
                'stable_subjects': sum(a >= 0.9 for a in accuracies),
                'overall_stability_status': status,
            }
        }


class InferenceModule:
    """Main inference module coordinator"""

    def __init__(self, architecture: PipelineArchitecture):
        self.arch = architecture
        self.prescription_matcher = PrescriptionMatcher(architecture.data_path / FORMULARY_FILE)
        self.navigation_analyzer = NavigationAnalyzer()
        self.telemetry_analyzer = TelemetryAnalyzer()

    def _record(self, modality: DataModality, inference_type: str, results: Dict[str, Any]):
        self.arch.record_lineage_event(new_event(
            ProcessingStage.INFERENCE, modality,
            hashlib.sha256(json.dumps(results, sort_keys=True, default=str).encode()).hexdigest(),
            {'inference_type': inference_type, 'results_summary': results['summary']}))

    def run_complete_inference(self, ingestion_results: Dict[str, Any],
                               redacted_df: Optional[pd.DataFrame] = None,
                               access: Optional[Dict[str, bool]] = None) -> Dict[str, Any]:
        """Run inference on every modality the role may read; healthcare only after redaction"""
        logger.info("Starting complete inference analysis")
        access = access or {}

        inference_results = {
            'prescription_matching': None,
            'barcode_robustness': None,
            'navigation_analysis': None,
            'telemetry_analysis': None,
            'skipped': {},
            'cross_modal_insights': {}
        }

        # Prescription matching (on the redacted records only)
        barcodes = ingestion_results['barcodes']
        if redacted_df is None:
            inference_results['skipped']['prescription_matching'] = 'no redacted healthcare records'
        elif barcodes['status'] != 'success' or not access.get('barcode_data', True):
            inference_results['skipped']['prescription_matching'] = 'no barcode data'
        else:
            prescription_results = self.prescription_matcher.process_prescription_matching(redacted_df, barcodes['data'])
            inference_results['prescription_matching'] = prescription_results
            self._record(DataModality.BARCODE_IMAGE, 'prescription_matching', prescription_results)

        if barcodes['status'] == 'success' and access.get('barcode_data', True):
            inference_results['barcode_robustness'] = self.prescription_matcher.barcode_robustness(barcodes['data'])

        # Navigation analysis
        if ingestion_results['video_frames']['status'] == 'success' and access.get('navigation_data', True):
            navigation_results = self.navigation_analyzer.process_navigation_analysis(
                ingestion_results['video_frames']['data'], stage_dir=self.arch.staged_path / "navigation_frames")
            navigation_results['staged_keyframes'] = [self.arch.relative(p) for p in navigation_results['staged_keyframes']]
            inference_results['navigation_analysis'] = navigation_results
            self._record(DataModality.VIDEO_FRAME, 'navigation_analysis', navigation_results)
        else:
            inference_results['skipped']['navigation_analysis'] = 'no video frames or no access'

        # Telemetry analysis
        if ingestion_results['mhealth']['status'] == 'success' and access.get('telemetry_data', True):
            telemetry_results = self.telemetry_analyzer.analyze_stability_metrics(ingestion_results['mhealth']['data'])
            inference_results['telemetry_analysis'] = telemetry_results
            self._record(DataModality.MHEALTH_TELEMETRY, 'telemetry_analysis', telemetry_results)
        else:
            inference_results['skipped']['telemetry_analysis'] = 'no telemetry or no access'

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

        if results['prescription_matching']:
            summary = results['prescription_matching']['summary']
            if summary['match_success_rate'] < 0.8:
                insights['risk_factors'].append(
                    f"{1 - summary['match_success_rate']:.0%} of prescriptions have no verifiable label")
                insights['recommendations'].append('Label the remaining medications and add them to the formulary')
            if summary['labels_quarantined']:
                insights['risk_factors'].append(f"{summary['labels_quarantined']} label(s) carry personal data")
                insights['recommendations'].append('Withdraw labels that carry personal data and reprint them')

        if results['barcode_robustness'] and results['barcode_robustness']['overall_decode_rate'] < 0.7:
            insights['risk_factors'].append('Labels often fail to decode when blurred, covered or noisy')
            insights['recommendations'].append('Scan labels flat, in focus and well lit; prefer 2-D codes')

        if results['navigation_analysis']:
            summary = results['navigation_analysis']['summary']
            if summary['missed_yields_under_stress']:
                insights['risk_factors'].append(
                    f"{summary['missed_yields_under_stress']} missed yields when the view was degraded")
                insights['recommendations'].append('Slow down or stop when the camera view is blocked or dark')

        if results['telemetry_analysis']:
            if results['telemetry_analysis']['summary']['overall_stability_status'] == 'unstable':
                insights['risk_factors'].append('Motion monitor unreliable on held-out subjects')
                insights['recommendations'].append('Check mechanical components and sensors')

        # Overall delivery prediction
        if len(insights['risk_factors']) == 0:
            insights['delivery_success_prediction'] = 'high'
        elif len(insights['risk_factors']) <= 2:
            insights['delivery_success_prediction'] = 'medium'
        else:
            insights['delivery_success_prediction'] = 'low'

        return insights
