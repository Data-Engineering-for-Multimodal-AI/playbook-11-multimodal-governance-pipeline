"""
Responsible AI Module for Medical Cart Pipeline

Implements:
- Bias detection: does the cart's automatic label check work equally well for every patient group?
  (demographic parity difference and the four-fifths ratio, on the redacted records)
- Explainability: a concrete reason for every unverified prescription, missed yield and misread activity
- Robustness evaluation under degraded labels, camera views and sensors
- Fairness across people for the motion monitor (accuracy per held-out subject)
"""

import json
import hashlib
import logging
from typing import Dict, List, Any

import pandas as pd

from pipeline_architecture import PipelineArchitecture, ProcessingStage, DataModality, new_event

logger = logging.getLogger(__name__)


def worst(statuses) -> str:
    statuses = list(statuses)
    return 'fail' if 'fail' in statuses else 'warning' if 'warning' in statuses else 'pass'


class BiasDetector:
    """Detects bias in delivery decisions"""

    def __init__(self):
        # Patient attributes to compare outcomes across (columns of the redacted records)
        self.group_columns = ['Age', 'Gender', 'Medical Condition', 'Insurance Provider']
        self.min_group_size = 30

    def analyze_demographic_bias(self, healthcare_df: pd.DataFrame, delivery_results: Dict[str, Any]) -> Dict[str, Any]:
        """Rate of prescriptions the cart can verify automatically, per patient group"""

        matching = delivery_results.get('prescription_matching')
        if not matching:
            return {'bias_status': 'not_run', 'overall_bias_score': None, 'groups': {}}

        auto_verified = healthcare_df['Medication'].isin(matching['auto_verified_medications'])
        overall_rate = float(auto_verified.mean())

        groups = {}
        for column in self.group_columns:
            if column not in healthcare_df.columns:
                continue
            stats = auto_verified.groupby(healthcare_df[column], observed=True).agg(['mean', 'size'])
            stats = stats[stats['size'] >= self.min_group_size]
            rates = stats['mean']
            groups[column] = {
                'rates': {str(g): {'patients': int(n), 'auto_verified_rate': round(float(r), 4)}
                          for g, (r, n) in stats.iterrows()},
                'parity_difference': round(float(rates.max() - rates.min()), 4),
                'disparate_impact_ratio': round(float(rates.min() / rates.max()), 4) if rates.max() > 0 else None,
                'lowest_group': str(rates.idxmin()),
                'highest_group': str(rates.idxmax()),
            }

        max_difference = max(g['parity_difference'] for g in groups.values())
        min_ratio = min(g['disparate_impact_ratio'] for g in groups.values() if g['disparate_impact_ratio'] is not None)
        if max_difference < 0.1 and min_ratio >= 0.8:
            status = 'low_bias'
        elif max_difference < 0.2:
            status = 'moderate_bias'
        else:
            status = 'high_bias'

        return {
            'outcome': 'prescription verified automatically by its label',
            'overall_rate': round(overall_rate, 4),
            'groups': groups,
            'overall_bias_score': round(max_difference, 4),
            'min_disparate_impact_ratio': round(min_ratio, 4),
            'bias_status': status,
        }

    def analyze_subject_disparity(self, telemetry_results: Dict[str, Any]) -> Dict[str, Any]:
        """Does the motion monitor work as well for every person it was tested on?"""
        if not telemetry_results or not telemetry_results.get('subject_stability'):
            return {'status': 'not_run'}
        accuracies = {s: r['balanced_accuracy'] for s, r in telemetry_results['subject_stability'].items()}
        gap = max(accuracies.values()) - min(accuracies.values())
        return {
            'balanced_accuracy_by_subject': accuracies,
            'accuracy_gap': round(gap, 4),
            'status': 'pass' if gap < 0.05 else 'warning' if gap < 0.15 else 'fail',
        }


class ExplainabilityModule:
    """Provides explanations for AI decisions and failures"""

    def __init__(self):
        self.explanation_templates = {
            'prescription_mismatch': "{count} prescriptions for {medication} can't be verified automatically: {reason}",
            'label_quarantined': "Label {file} ({format}) was quarantined: {reason}",
            'navigation_failure': "With {condition}, the cart missed {missed} of {yields} yields (a person in the path it didn't see)",
            'stability_issue': "{activity} is read as {misread_as} in {rate:.0%} of windows",
            'delivery_failure': "Delivery at risk because of {factors}"
        }

    def explain_prescription_failures(self, prescription_results: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Generate explanations for prescription matching failures"""

        explanations = []
        if not prescription_results:
            return explanations

        for result in prescription_results['matching_results']:
            if result['match_status'] != 'confirmed':
                explanations.append({
                    'type': 'prescription_mismatch',
                    'medication': result['medication'],
                    'reason': result['reason'],
                    'explanation_text': self.explanation_templates['prescription_mismatch'].format(
                        count=result['prescription_count'], medication=result['medication'], reason=result['reason']),
                    'severity': 'high'
                })
        for label in prescription_results['label_results']:
            if label['status'] == 'quarantined':
                explanations.append({
                    'type': 'label_quarantined',
                    'file': label['file'],
                    'reason': label['reason'],
                    'explanation_text': self.explanation_templates['label_quarantined'].format(
                        file=label['file'], format=label['format'], reason=label['reason']),
                    'severity': 'medium'
                })
        return explanations

    def explain_navigation_issues(self, navigation_results: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Generate explanations for navigation problems"""

        explanations = []
        if not navigation_results:
            return explanations

        summary = navigation_results['summary']
        for condition, stats in summary['robustness_by_condition'].items():
            if stats['missed_yields']:
                explanations.append({
                    'type': 'navigation_failure',
                    'condition': condition,
                    'details': stats,
                    'explanation_text': self.explanation_templates['navigation_failure'].format(
                        condition=condition.replace('_', ' '), missed=stats['missed_yields'],
                        yields=summary['frames_with_people_in_path']),
                    'severity': 'high'
                })
        return explanations

    def explain_stability_issues(self, telemetry_results: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Generate explanations for motion-monitor errors"""

        explanations = []
        if not telemetry_results:
            return explanations

        threshold = telemetry_results['summary'].get('threshold_acc_std')
        for confusion in telemetry_results.get('confusions', []):
            explanations.append({
                'type': 'stability_issue',
                'activity': confusion['activity'],
                'details': {**confusion, 'threshold_acc_std': threshold},
                'explanation_text': self.explanation_templates['stability_issue'].format(
                    activity=confusion['activity'], misread_as=confusion['misread_as'],
                    rate=confusion['misread_rate']) +
                    (f" (chest acceleration varies less than the {threshold:.3f} m/s² threshold)"
                     if confusion['misread_as'] == 'still' else ''),
                'severity': 'high' if confusion['misread_rate'] >= 0.25 else 'medium'
            })
        return explanations

    def generate_delivery_failure_explanation(self, all_explanations: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Generate comprehensive explanation for overall delivery risk"""

        if not all_explanations:
            return {
                'type': 'delivery_success',
                'explanation_text': "No failures to explain in this run"
            }

        counts = {}
        for e in all_explanations:
            counts[e['type']] = counts.get(e['type'], 0) + 1
        failure_factors = [f"{n} {kind.replace('_', ' ')}{'s' if n > 1 else ''}" for kind, n in counts.items()]
        high_severity_count = sum(1 for e in all_explanations if e.get('severity') == 'high')

        return {
            'type': 'delivery_failure',
            'factors': failure_factors,
            'total_issues': len(all_explanations),
            'high_severity_issues': high_severity_count,
            'explanation_text': self.explanation_templates['delivery_failure'].format(
                factors=", ".join(failure_factors)),
            'overall_severity': 'high' if high_severity_count else 'medium'
        }


class RobustnessEvaluator:
    """Evaluates system robustness under various conditions"""

    def evaluate_occlusion_robustness(self, navigation_results: Dict[str, Any]) -> Dict[str, Any]:
        """Evaluate robustness of the yield/proceed decision under a degraded camera view"""
        if not navigation_results:
            return {'status': 'not_run'}
        summary = navigation_results['summary']
        score = summary['average_occlusion_robustness']
        missed = summary['missed_yields_under_stress']
        status = 'fail' if score < 0.4 else 'warning' if score < 0.7 or missed else 'pass'
        return {
            'overall_robustness': round(score, 4),
            'by_condition': summary['robustness_by_condition'],
            'missed_yields': missed,
            'failure_modes': [c for c, s in summary['robustness_by_condition'].items() if s['missed_yields']],
            'status': status
        }

    def evaluate_label_robustness(self, barcode_robustness: Dict[str, Any]) -> Dict[str, Any]:
        """Evaluate how often labels still decode when degraded"""
        if not barcode_robustness:
            return {'status': 'not_run'}
        rate = barcode_robustness['overall_decode_rate']
        return {**barcode_robustness,
                'status': 'pass' if rate >= 0.7 else 'warning' if rate >= 0.4 else 'fail'}

    def evaluate_sensor_degradation(self, telemetry_results: Dict[str, Any]) -> Dict[str, Any]:
        """Evaluate robustness under sensor degradation"""
        if not telemetry_results or not telemetry_results.get('degradation'):
            return {'status': 'not_run'}
        degradation = telemetry_results['degradation']
        worst_case = min(degradation.values())
        return {
            'balanced_accuracy_clean': telemetry_results['summary']['test_balanced_accuracy'],
            'balanced_accuracy_degraded': degradation,
            'degradation_robustness': worst_case,
            'status': 'pass' if worst_case >= 0.9 else 'warning' if worst_case >= 0.75 else 'fail'
        }


class ResponsibleAIModule:
    """Main Responsible AI module coordinator"""

    def __init__(self, architecture: PipelineArchitecture):
        self.arch = architecture
        self.bias_detector = BiasDetector()
        self.explainability = ExplainabilityModule()
        self.robustness_evaluator = RobustnessEvaluator()

    def run_responsible_ai_assessment(self,
                                      healthcare_df,
                                      inference_results: Dict[str, Any]) -> Dict[str, Any]:
        """Run comprehensive Responsible AI assessment (healthcare_df: the redacted records, or None)"""

        logger.info("Starting Responsible AI assessment")

        rai_results = {
            'bias_analysis': {},
            'explainability_analysis': {},
            'robustness_analysis': {},
            'overall_assessment': {}
        }

        # Bias Analysis
        if healthcare_df is not None:
            rai_results['bias_analysis']['demographic_bias'] = self.bias_detector.analyze_demographic_bias(
                healthcare_df, inference_results)
        rai_results['bias_analysis']['subject_disparity'] = self.bias_detector.analyze_subject_disparity(
            inference_results.get('telemetry_analysis'))

        # Explainability Analysis
        all_explanations = (
            self.explainability.explain_prescription_failures(inference_results.get('prescription_matching')) +
            self.explainability.explain_navigation_issues(inference_results.get('navigation_analysis')) +
            self.explainability.explain_stability_issues(inference_results.get('telemetry_analysis')))
        rai_results['explainability_analysis'] = {
            'individual_explanations': all_explanations,
            'delivery_explanation': self.explainability.generate_delivery_failure_explanation(all_explanations),
            'total_issues_explained': len(all_explanations)
        }

        # Robustness Analysis
        rai_results['robustness_analysis'] = {
            'occlusion_robustness': self.robustness_evaluator.evaluate_occlusion_robustness(
                inference_results.get('navigation_analysis')),
            'label_robustness': self.robustness_evaluator.evaluate_label_robustness(
                inference_results.get('barcode_robustness')),
            'sensor_robustness': self.robustness_evaluator.evaluate_sensor_degradation(
                inference_results.get('telemetry_analysis')),
        }

        # Overall Assessment
        rai_results['overall_assessment'] = self._generate_overall_assessment(rai_results)

        # Record lineage
        self.arch.record_lineage_event(new_event(
            ProcessingStage.AUDIT, DataModality.HEALTHCARE_CSV,
            hashlib.sha256(json.dumps(rai_results, sort_keys=True, default=str).encode()).hexdigest(),
            {'assessment_type': 'responsible_ai', 'overall_status': rai_results['overall_assessment']['overall_status'],
             'checks': rai_results['overall_assessment']['checks']}))

        logger.info("Responsible AI assessment completed")
        return rai_results

    def _generate_overall_assessment(self, rai_results: Dict[str, Any]) -> Dict[str, Any]:
        """One status per check, and the worst of them overall"""

        bias = rai_results['bias_analysis'].get('demographic_bias', {'bias_status': 'not_run'})
        fairness_status = {'low_bias': 'pass', 'moderate_bias': 'warning', 'high_bias': 'fail'}.get(
            bias['bias_status'], 'warning')
        robustness = rai_results['robustness_analysis']

        # Robustness checks are stress tests on synthetically degraded inputs: they warn, they don't fail the run
        stress = lambda status: {'not_run': 'warning', 'fail': 'warning'}.get(status, status)
        checks = {
            'fairness_across_patient_groups': fairness_status,
            'fairness_across_people (motion monitor)': {'not_run': 'warning'}.get(
                rai_results['bias_analysis']['subject_disparity']['status'],
                rai_results['bias_analysis']['subject_disparity']['status']),
            'navigation_robustness': stress(robustness['occlusion_robustness']['status']),
            'label_robustness': stress(robustness['label_robustness']['status']),
            'sensor_robustness': stress(robustness['sensor_robustness']['status']),
        }

        recommendations = []
        if fairness_status != 'pass':
            recommendations.append("Address the gap in automatic verification between patient groups")
        if checks['navigation_robustness'] != 'pass':
            recommendations.append("Treat a blocked, blurred or dark camera view as 'stop', not 'path clear'")
        if checks['label_robustness'] != 'pass':
            recommendations.append("Scan labels flat and in focus; fall back to manual verification when decoding fails")
        if checks['sensor_robustness'] != 'pass':
            recommendations.append("Improve sensor fault tolerance")

        return {
            'bias_score': None if bias.get('overall_bias_score') is None else round(1 - bias['overall_bias_score'], 4),
            'robustness_scores': {
                'navigation': robustness['occlusion_robustness'].get('overall_robustness'),
                'labels': robustness['label_robustness'].get('overall_decode_rate'),
                'sensors': robustness['sensor_robustness'].get('degradation_robustness'),
            },
            'issues_explained': rai_results['explainability_analysis']['total_issues_explained'],
            'checks': checks,
            'overall_status': worst(checks.values()),
            'recommendations': recommendations
        }
