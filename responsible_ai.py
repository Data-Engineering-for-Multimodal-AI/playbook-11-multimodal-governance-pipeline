"""
Responsible AI Module for Medical Cart Pipeline

Implements:
- Bias detection in navigation route choices
- Explainability for failed deliveries
- Robustness evaluation under various conditions
- Fairness assessment across different scenarios
"""

import pandas as pd
import numpy as np
import json
import uuid
import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
import logging
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import KMeans
import hashlib

from pipeline_architecture import PipelineArchitecture, LineageEvent, ProcessingStage, DataModality

logger = logging.getLogger(__name__)

class BiasDetector:
    """Detects bias in navigation and delivery decisions"""
    
    def __init__(self):
        self.bias_categories = [
            'patient_demographics',
            'medication_type',
            'location_based',
            'time_based'
        ]
    
    def analyze_demographic_bias(self, healthcare_df: pd.DataFrame, delivery_results: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze bias in delivery success based on patient demographics"""
        
        bias_analysis = {
            'age_bias': {},
            'gender_bias': {},
            'condition_bias': {},
            'overall_bias_score': 0.0
        }
        
        # Simulate delivery success rates based on prescription matching
        if 'prescription_matching' in delivery_results:
            match_results = delivery_results['prescription_matching']['matching_results']
            
            # Create delivery success mapping
            delivery_success = {}
            for result in match_results:
                medication = result['medication']
                success_rate = result['overall_confidence']
                delivery_success[medication] = success_rate > 0.7
        
        # Age bias analysis
        if 'Age' in healthcare_df.columns:
            age_groups = healthcare_df['Age'].value_counts().to_dict()
            
            for age_group in age_groups:
                age_subset = healthcare_df[healthcare_df['Age'] == age_group]
                medications_in_group = age_subset['Medication'].unique()
                
                success_rate = np.mean([
                    delivery_success.get(med, 0.5) for med in medications_in_group
                    if med in delivery_success
                ])
                
                bias_analysis['age_bias'][str(age_group)] = {
                    'patient_count': len(age_subset),
                    'success_rate': success_rate,
                    'deviation_from_mean': success_rate - 0.7  # Assuming 0.7 is target
                }
        
        # Gender bias analysis
        if 'Gender' in healthcare_df.columns:
            gender_groups = healthcare_df['Gender'].value_counts().to_dict()
            
            for gender in gender_groups:
                gender_subset = healthcare_df[healthcare_df['Gender'] == gender]
                medications_in_group = gender_subset['Medication'].unique()
                
                success_rate = np.mean([
                    delivery_success.get(med, 0.5) for med in medications_in_group
                    if med in delivery_success
                ])
                
                bias_analysis['gender_bias'][gender] = {
                    'patient_count': len(gender_subset),
                    'success_rate': success_rate,
                    'deviation_from_mean': success_rate - 0.7
                }
        
        # Medical condition bias analysis
        if 'Medical Condition' in healthcare_df.columns:
            condition_groups = healthcare_df['Medical Condition'].value_counts().to_dict()
            
            for condition in list(condition_groups.keys())[:5]:  # Top 5 conditions
                condition_subset = healthcare_df[healthcare_df['Medical Condition'] == condition]
                medications_in_group = condition_subset['Medication'].unique()
                
                success_rate = np.mean([
                    delivery_success.get(med, 0.5) for med in medications_in_group
                    if med in delivery_success
                ])
                
                bias_analysis['condition_bias'][condition] = {
                    'patient_count': len(condition_subset),
                    'success_rate': success_rate,
                    'deviation_from_mean': success_rate - 0.7
                }
        
        # Calculate overall bias score
        all_deviations = []
        for category in ['age_bias', 'gender_bias', 'condition_bias']:
            for group_data in bias_analysis[category].values():
                if isinstance(group_data, dict) and 'deviation_from_mean' in group_data:
                    all_deviations.append(abs(group_data['deviation_from_mean']))
        
        bias_analysis['overall_bias_score'] = np.mean(all_deviations) if all_deviations else 0.0
        bias_analysis['bias_status'] = (
            'low_bias' if bias_analysis['overall_bias_score'] < 0.1 else
            'moderate_bias' if bias_analysis['overall_bias_score'] < 0.2 else
            'high_bias'
        )
        
        return bias_analysis
    
    def analyze_route_bias(self, navigation_results: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze bias in navigation route choices"""
        
        route_bias = {
            'corridor_width_preference': {},
            'complexity_preference': {},
            'temporal_bias': {},
            'route_bias_score': 0.0
        }
        
        if 'navigation_analysis' in navigation_results:
            nav_data = navigation_results['navigation_analysis']
            
            # Analyze corridor width preferences
            width_ratios = [frame['corridor_width_ratio'] for frame in nav_data if 'corridor_width_ratio' in frame]
            complexity_scores = [frame['navigation_complexity'] for frame in nav_data if 'navigation_complexity' in frame]
            
            if width_ratios:
                route_bias['corridor_width_preference'] = {
                    'mean_width_ratio': np.mean(width_ratios),
                    'width_variance': np.var(width_ratios),
                    'preference_bias': abs(np.mean(width_ratios) - 0.5)  # 0.5 would be no preference
                }
            
            if complexity_scores:
                route_bias['complexity_preference'] = {
                    'mean_complexity': np.mean(complexity_scores),
                    'complexity_variance': np.var(complexity_scores),
                    'avoidance_bias': np.mean(complexity_scores)  # Lower means avoiding complex routes
                }
            
            # Temporal bias (preference for certain times)
            timestamps = [frame['timestamp'] for frame in nav_data if 'timestamp' in frame]
            if timestamps:
                time_distribution = np.histogram(timestamps, bins=10)[0]
                route_bias['temporal_bias'] = {
                    'time_distribution_variance': np.var(time_distribution),
                    'temporal_clustering': np.max(time_distribution) / np.mean(time_distribution)
                }
            
            # Calculate overall route bias score
            bias_components = []
            if 'corridor_width_preference' in route_bias and route_bias['corridor_width_preference']:
                bias_components.append(route_bias['corridor_width_preference']['preference_bias'])
            if 'complexity_preference' in route_bias and route_bias['complexity_preference']:
                bias_components.append(route_bias['complexity_preference']['avoidance_bias'])
            
            route_bias['route_bias_score'] = np.mean(bias_components) if bias_components else 0.0
        
        return route_bias

class ExplainabilityModule:
    """Provides explanations for AI decisions and failures"""
    
    def __init__(self):
        self.explanation_templates = {
            'prescription_mismatch': "Prescription for {medication} could not be matched due to {reason}",
            'navigation_failure': "Navigation failed due to {obstacle_type} with confidence {confidence}",
            'stability_issue': "Cart instability detected: {sensor_type} variance exceeded threshold by {factor}x",
            'delivery_failure': "Delivery failed due to combination of {factors}"
        }
    
    def explain_prescription_failures(self, prescription_results: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Generate explanations for prescription matching failures"""
        
        explanations = []
        
        if 'matching_results' in prescription_results:
            for result in prescription_results['matching_results']:
                if result['match_result']['match_status'] != 'confirmed':
                    
                    # Determine failure reason
                    if result['scan_confidence'] < 0.5:
                        reason = "poor barcode scan quality"
                    elif result['match_result']['similarity_score'] < 0.3:
                        reason = "medication name similarity too low"
                    elif result['expected_barcode_type'] == 'unknown':
                        reason = "unknown barcode format"
                    else:
                        reason = "insufficient matching confidence"
                    
                    explanation = {
                        'type': 'prescription_mismatch',
                        'medication': result['medication'],
                        'reason': reason,
                        'details': {
                            'scan_confidence': result['scan_confidence'],
                            'match_confidence': result['match_result']['match_confidence'],
                            'similarity_score': result['match_result']['similarity_score']
                        },
                        'explanation_text': self.explanation_templates['prescription_mismatch'].format(
                            medication=result['medication'],
                            reason=reason
                        ),
                        'severity': 'high' if result['match_result']['match_status'] == 'no_match' else 'medium'
                    }
                    explanations.append(explanation)
        
        return explanations
    
    def explain_navigation_issues(self, navigation_results: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Generate explanations for navigation problems"""
        
        explanations = []
        
        if 'robustness_analysis' in navigation_results:
            for frame_result in navigation_results['robustness_analysis']:
                if frame_result['robustness_status'] == 'poor':
                    
                    # Determine issue type
                    if frame_result['central_occlusion_robustness'] < 0.3:
                        issue_type = "central obstacle blocking"
                    elif frame_result['side_occlusion_robustness'] < 0.3:
                        issue_type = "side visibility obstruction"
                    else:
                        issue_type = "general navigation complexity"
                    
                    explanation = {
                        'type': 'navigation_failure',
                        'frame_number': frame_result['frame_number'],
                        'issue_type': issue_type,
                        'details': {
                            'central_robustness': frame_result['central_occlusion_robustness'],
                            'side_robustness': frame_result['side_occlusion_robustness'],
                            'occlusion_level': frame_result['occlusion_level']
                        },
                        'explanation_text': self.explanation_templates['navigation_failure'].format(
                            obstacle_type=issue_type,
                            confidence=f"{frame_result['average_robustness']:.2f}"
                        ),
                        'severity': 'high' if frame_result['average_robustness'] < 0.3 else 'medium'
                    }
                    explanations.append(explanation)
        
        return explanations
    
    def explain_stability_issues(self, telemetry_results: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Generate explanations for cart stability problems"""
        
        explanations = []
        
        if 'subject_stability' in telemetry_results:
            for subject_id, stability_data in telemetry_results['subject_stability'].items():
                if stability_data['stability_status'] == 'unstable':
                    
                    # Identify primary instability cause
                    if stability_data['high_variance_detected']:
                        sensor_type = "acceleration"
                        factor = stability_data['acceleration_variance'] / 2.0
                    elif stability_data['gyro_variance'] > 1.5:
                        sensor_type = "gyroscope"
                        factor = stability_data['gyro_variance'] / 1.5
                    else:
                        sensor_type = "general motion"
                        factor = 1.0
                    
                    explanation = {
                        'type': 'stability_issue',
                        'subject_id': subject_id,
                        'sensor_type': sensor_type,
                        'details': {
                            'acceleration_variance': stability_data['acceleration_variance'],
                            'gyro_variance': stability_data['gyro_variance'],
                            'stability_score': stability_data['stability_score'],
                            'missing_data_ratio': stability_data['missing_data_ratio']
                        },
                        'explanation_text': self.explanation_templates['stability_issue'].format(
                            sensor_type=sensor_type,
                            factor=f"{factor:.1f}"
                        ),
                        'severity': 'high' if stability_data['stability_score'] < 0.3 else 'medium'
                    }
                    explanations.append(explanation)
        
        return explanations
    
    def generate_delivery_failure_explanation(self, all_explanations: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Generate comprehensive explanation for overall delivery failure"""
        
        if not all_explanations:
            return {
                'type': 'delivery_success',
                'explanation_text': "All systems functioning normally, delivery expected to succeed",
                'confidence': 0.9
            }
        
        # Categorize failures
        prescription_failures = [e for e in all_explanations if e['type'] == 'prescription_mismatch']
        navigation_failures = [e for e in all_explanations if e['type'] == 'navigation_failure']
        stability_failures = [e for e in all_explanations if e['type'] == 'stability_issue']
        
        failure_factors = []
        if prescription_failures:
            failure_factors.append(f"{len(prescription_failures)} prescription matching issues")
        if navigation_failures:
            failure_factors.append(f"{len(navigation_failures)} navigation problems")
        if stability_failures:
            failure_factors.append(f"{len(stability_failures)} stability concerns")
        
        # Determine overall severity
        high_severity_count = sum(1 for e in all_explanations if e.get('severity') == 'high')
        overall_severity = 'high' if high_severity_count > 0 else 'medium'
        
        return {
            'type': 'delivery_failure',
            'factors': failure_factors,
            'total_issues': len(all_explanations),
            'high_severity_issues': high_severity_count,
            'explanation_text': self.explanation_templates['delivery_failure'].format(
                factors=", ".join(failure_factors)
            ),
            'overall_severity': overall_severity,
            'confidence': 0.8 if overall_severity == 'high' else 0.6
        }

class RobustnessEvaluator:
    """Evaluates system robustness under various conditions"""
    
    def __init__(self):
        self.test_conditions = [
            'partial_occlusion',
            'sensor_degradation',
            'network_latency',
            'environmental_changes'
        ]
    
    def evaluate_occlusion_robustness(self, navigation_results: Dict[str, Any]) -> Dict[str, Any]:
        """Evaluate robustness under visual occlusion"""
        
        occlusion_test = {
            'test_scenarios': [],
            'overall_robustness': 0.0,
            'failure_modes': []
        }
        
        if 'robustness_analysis' in navigation_results:
            robustness_scores = []
            
            for frame_result in navigation_results['robustness_analysis']:
                scenario = {
                    'frame_number': frame_result['frame_number'],
                    'occlusion_level': frame_result['occlusion_level'],
                    'central_robustness': frame_result['central_occlusion_robustness'],
                    'side_robustness': frame_result['side_occlusion_robustness'],
                    'average_robustness': frame_result['average_robustness'],
                    'status': frame_result['robustness_status']
                }
                
                occlusion_test['test_scenarios'].append(scenario)
                robustness_scores.append(frame_result['average_robustness'])
                
                # Identify failure modes
                if frame_result['robustness_status'] == 'poor':
                    if frame_result['central_occlusion_robustness'] < 0.4:
                        occlusion_test['failure_modes'].append('central_vision_dependency')
                    if frame_result['side_occlusion_robustness'] < 0.4:
                        occlusion_test['failure_modes'].append('peripheral_vision_dependency')
            
            occlusion_test['overall_robustness'] = np.mean(robustness_scores) if robustness_scores else 0.0
            occlusion_test['robustness_variance'] = np.var(robustness_scores) if robustness_scores else 0.0
        
        return occlusion_test
    
    def evaluate_sensor_degradation(self, telemetry_results: Dict[str, Any]) -> Dict[str, Any]:
        """Evaluate robustness under sensor degradation"""
        
        degradation_test = {
            'missing_data_tolerance': {},
            'sensor_failure_modes': [],
            'degradation_robustness': 0.0
        }
        
        if 'subject_stability' in telemetry_results:
            missing_data_ratios = []
            stability_scores = []
            
            for subject_id, stability_data in telemetry_results['subject_stability'].items():
                missing_ratio = stability_data['missing_data_ratio']
                stability_score = stability_data['stability_score']
                
                missing_data_ratios.append(missing_ratio)
                stability_scores.append(stability_score)
                
                degradation_test['missing_data_tolerance'][subject_id] = {
                    'missing_data_ratio': missing_ratio,
                    'stability_maintained': stability_score > 0.5,
                    'degradation_impact': max(0, 0.8 - stability_score)  # Baseline 0.8
                }
                
                # Identify failure modes
                if missing_ratio > 0.2 and stability_score < 0.4:
                    degradation_test['sensor_failure_modes'].append('high_data_loss_instability')
                elif missing_ratio > 0.1 and stability_score < 0.6:
                    degradation_test['sensor_failure_modes'].append('moderate_data_loss_degradation')
            
            # Calculate overall degradation robustness
            if stability_scores:
                # Robustness inversely related to impact of missing data
                avg_impact = np.mean([
                    data['degradation_impact'] 
                    for data in degradation_test['missing_data_tolerance'].values()
                ])
                degradation_test['degradation_robustness'] = max(0, 1.0 - avg_impact)
        
        return degradation_test

class ResponsibleAIModule:
    """Main Responsible AI module coordinator"""
    
    def __init__(self, architecture: PipelineArchitecture):
        self.arch = architecture
        self.bias_detector = BiasDetector()
        self.explainability = ExplainabilityModule()
        self.robustness_evaluator = RobustnessEvaluator()
    
    def run_responsible_ai_assessment(self, 
                                    healthcare_df: pd.DataFrame, 
                                    inference_results: Dict[str, Any]) -> Dict[str, Any]:
        """Run comprehensive Responsible AI assessment"""
        
        logger.info("Starting Responsible AI assessment")
        
        rai_results = {
            'bias_analysis': {},
            'explainability_analysis': {},
            'robustness_analysis': {},
            'overall_assessment': {}
        }
        
        # Bias Analysis
        if 'prescription_matching' in inference_results:
            demographic_bias = self.bias_detector.analyze_demographic_bias(
                healthcare_df, inference_results
            )
            rai_results['bias_analysis']['demographic_bias'] = demographic_bias
        
        if 'navigation_analysis' in inference_results:
            route_bias = self.bias_detector.analyze_route_bias(inference_results)
            rai_results['bias_analysis']['route_bias'] = route_bias
        
        # Explainability Analysis
        all_explanations = []
        
        if 'prescription_matching' in inference_results:
            prescription_explanations = self.explainability.explain_prescription_failures(
                inference_results['prescription_matching']
            )
            all_explanations.extend(prescription_explanations)
        
        if 'navigation_analysis' in inference_results:
            navigation_explanations = self.explainability.explain_navigation_issues(
                inference_results['navigation_analysis']
            )
            all_explanations.extend(navigation_explanations)
        
        if 'telemetry_analysis' in inference_results:
            stability_explanations = self.explainability.explain_stability_issues(
                inference_results['telemetry_analysis']
            )
            all_explanations.extend(stability_explanations)
        
        # Generate overall delivery explanation
        delivery_explanation = self.explainability.generate_delivery_failure_explanation(
            all_explanations
        )
        
        rai_results['explainability_analysis'] = {
            'individual_explanations': all_explanations,
            'delivery_explanation': delivery_explanation,
            'total_issues_explained': len(all_explanations)
        }
        
        # Robustness Analysis
        if 'navigation_analysis' in inference_results:
            occlusion_robustness = self.robustness_evaluator.evaluate_occlusion_robustness(
                inference_results['navigation_analysis']
            )
            rai_results['robustness_analysis']['occlusion_robustness'] = occlusion_robustness
        
        if 'telemetry_analysis' in inference_results:
            sensor_robustness = self.robustness_evaluator.evaluate_sensor_degradation(
                inference_results['telemetry_analysis']
            )
            rai_results['robustness_analysis']['sensor_robustness'] = sensor_robustness
        
        # Overall Assessment
        rai_results['overall_assessment'] = self._generate_overall_assessment(rai_results)
        
        # Record lineage
        event = LineageEvent(
            event_id=str(uuid.uuid4()),
            timestamp=datetime.datetime.now().isoformat(),
            stage=ProcessingStage.AUDIT,
            modality=DataModality.HEALTHCARE_CSV,  # Representative
            data_hash=hashlib.sha256(str(rai_results).encode()).hexdigest(),
            previous_hash="",
            metadata={
                'assessment_type': 'responsible_ai',
                'overall_status': rai_results['overall_assessment']['overall_status']
            }
        )
        self.arch.record_lineage_event(event)
        
        logger.info("Responsible AI assessment completed")
        return rai_results
    
    def _generate_overall_assessment(self, rai_results: Dict[str, Any]) -> Dict[str, Any]:
        """Generate overall Responsible AI assessment"""
        
        assessment = {
            'bias_score': 0.0,
            'explainability_score': 0.0,
            'robustness_score': 0.0,
            'overall_score': 0.0,
            'overall_status': 'unknown',
            'recommendations': []
        }
        
        # Bias scoring
        if 'bias_analysis' in rai_results:
            bias_scores = []
            
            if 'demographic_bias' in rai_results['bias_analysis']:
                demo_bias = rai_results['bias_analysis']['demographic_bias']
                bias_score = 1.0 - demo_bias['overall_bias_score']  # Invert so higher is better
                bias_scores.append(bias_score)
                
                if demo_bias['bias_status'] == 'high_bias':
                    assessment['recommendations'].append("Address demographic bias in delivery success rates")
            
            assessment['bias_score'] = np.mean(bias_scores) if bias_scores else 0.8
        
        # Explainability scoring
        if 'explainability_analysis' in rai_results:
            exp_data = rai_results['explainability_analysis']
            total_issues = exp_data['total_issues_explained']
            
            # Score based on ability to explain issues
            if total_issues == 0:
                assessment['explainability_score'] = 1.0  # No issues to explain
            else:
                # Score based on explanation quality
                high_severity = sum(1 for e in exp_data['individual_explanations'] if e.get('severity') == 'high')
                explanation_coverage = 1.0 - (high_severity / max(total_issues, 1))
                assessment['explainability_score'] = explanation_coverage
                
                if explanation_coverage < 0.7:
                    assessment['recommendations'].append("Improve explanation quality for critical failures")
        
        # Robustness scoring
        if 'robustness_analysis' in rai_results:
            robustness_scores = []
            
            if 'occlusion_robustness' in rai_results['robustness_analysis']:
                occlusion_score = rai_results['robustness_analysis']['occlusion_robustness']['overall_robustness']
                robustness_scores.append(occlusion_score)
                
                if occlusion_score < 0.6:
                    assessment['recommendations'].append("Enhance visual robustness algorithms")
            
            if 'sensor_robustness' in rai_results['robustness_analysis']:
                sensor_score = rai_results['robustness_analysis']['sensor_robustness']['degradation_robustness']
                robustness_scores.append(sensor_score)
                
                if sensor_score < 0.6:
                    assessment['recommendations'].append("Improve sensor fault tolerance")
            
            assessment['robustness_score'] = np.mean(robustness_scores) if robustness_scores else 0.8
        
        # Overall scoring
        scores = [assessment['bias_score'], assessment['explainability_score'], assessment['robustness_score']]
        assessment['overall_score'] = np.mean([s for s in scores if s > 0])
        
        # Determine overall status
        if assessment['overall_score'] >= 0.8:
            assessment['overall_status'] = 'excellent'
        elif assessment['overall_score'] >= 0.6:
            assessment['overall_status'] = 'good'
        elif assessment['overall_score'] >= 0.4:
            assessment['overall_status'] = 'adequate'
        else:
            assessment['overall_status'] = 'needs_improvement'
        
        return assessment

if __name__ == "__main__":
    # Test Responsible AI module
    arch = PipelineArchitecture("/Users/vasundras/Desktop/pb-11-mmgovernancepipeline")
    rai = ResponsibleAIModule(arch)
    
    print("Responsible AI module test completed")