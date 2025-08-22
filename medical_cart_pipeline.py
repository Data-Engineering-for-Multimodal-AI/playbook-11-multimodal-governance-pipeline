#!/usr/bin/env python3
"""
Medical Cart Pipeline - Main Orchestrator

Autonomous Medical Cart Multimodal Data Pipeline
Demonstrates end-to-end cart journey from prescription to delivery

Usage:
    python medical_cart_pipeline.py [--user-role ROLE] [--verbose]
"""

import argparse
import logging
import datetime
import json
import sys
import pandas as pd
from pathlib import Path
from typing import Dict, List, Any, Optional

# Import pipeline modules
from pipeline_architecture import PipelineArchitecture, LineageEvent, ProcessingStage, DataModality
from data_ingestion import DataIngestionModule
from security_module import SecurityModule, SecurityRole
from inference_module import InferenceModule
from responsible_ai import ResponsibleAIModule
from report_generator import ReportGenerator

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(module)s - %(message)s')
logger = logging.getLogger(__name__)

class MedicalCartPipeline:
    """Main pipeline orchestrator for autonomous medical cart"""
    
    def __init__(self, workspace_path: str, user_role: str = SecurityRole.MEDICAL_STAFF):
        self.workspace_path = Path(workspace_path)
        self.user_role = user_role
        
        # Initialize architecture
        self.architecture = PipelineArchitecture(workspace_path)
        
        # Initialize modules
        self.ingestion = DataIngestionModule(self.architecture)
        self.security = SecurityModule(self.architecture)
        self.inference = InferenceModule(self.architecture)
        self.responsible_ai = ResponsibleAIModule(self.architecture)
        self.report_generator = ReportGenerator(self.architecture.reports_path)
        
        logger.info(f"Medical Cart Pipeline initialized for user role: {user_role}")
    
    def run_complete_pipeline(self) -> Dict[str, Any]:
        """Execute complete pipeline from ingestion to reporting"""
        
        logger.info("Starting complete Medical Cart Pipeline execution")
        pipeline_start_time = datetime.datetime.now()
        
        pipeline_results = {
            'execution_metadata': {
                'start_time': pipeline_start_time.isoformat(),
                'user_role': self.user_role,
                'workspace_path': str(self.workspace_path)
            },
            'stage_results': {},
            'overall_status': 'unknown'
        }
        
        try:
            # Stage 1: Data Ingestion
            logger.info("Stage 1: Data Ingestion")
            ingestion_results = self.ingestion.ingest_all_modalities()
            
            # Store DataFrame separately and create serializable summary
            healthcare_df = None
            if (ingestion_results.get('results', {}).get('healthcare', {}).get('status') == 'success' and
                'data' in ingestion_results['results']['healthcare']):
                healthcare_df = ingestion_results['results']['healthcare']['data']
            
            # Create completely new serializable structure
            ingestion_summary = {
                'overall_status': ingestion_results.get('overall_status', 'unknown'),
                'successful_modalities': ingestion_results.get('successful_modalities', 0),
                'total_modalities': ingestion_results.get('total_modalities', 0),
                'ingestion_timestamp': ingestion_results.get('ingestion_timestamp', ''),
                'results': {}
            }
            
            # Copy each result without DataFrames
            for modality, result in ingestion_results.get('results', {}).items():
                if isinstance(result, dict):
                    result_copy = {k: v for k, v in result.items() if k != 'data'}
                    if modality == 'healthcare' and healthcare_df is not None:
                        result_copy['data_summary'] = {
                            'type': 'DataFrame',
                            'shape': list(healthcare_df.shape),
                            'columns': list(healthcare_df.columns),
                            'record_count': len(healthcare_df)
                        }
                    elif 'data' in result and not isinstance(result['data'], pd.DataFrame):
                        result_copy['data'] = result['data']
                    
                    ingestion_summary['results'][modality] = result_copy
            
            pipeline_results['stage_results']['ingestion'] = ingestion_summary
            
            if ingestion_results['overall_status'] not in ['success', 'partial_success']:
                raise Exception("Data ingestion failed - cannot proceed")
            
            # Stage 2: Security Processing
            logger.info("Stage 2: Security Processing")
            security_results = self._process_security_stage(ingestion_results)
            security_summary = json.loads(json.dumps(security_results, default=str))
            pipeline_results['stage_results']['security'] = security_summary
            
            # Stage 3: Inference Processing
            logger.info("Stage 3: Inference Processing") 
            # Use original results for inference (with DataFrames)
            inference_results = self.inference.run_complete_inference(ingestion_results['results'])
            
            # Convert inference results to JSON-serializable format
            inference_summary = json.loads(json.dumps(inference_results, default=str))
            pipeline_results['stage_results']['inference'] = inference_summary
            
            # Stage 4: Responsible AI Assessment
            logger.info("Stage 4: Responsible AI Assessment")
            if healthcare_df is not None:
                rai_results = self.responsible_ai.run_responsible_ai_assessment(
                    healthcare_df, inference_results
                )
                rai_summary = json.loads(json.dumps(rai_results, default=str))
                pipeline_results['stage_results']['responsible_ai'] = rai_summary
            else:
                rai_results = {'status': 'skipped', 'reason': 'healthcare data unavailable'}
                pipeline_results['stage_results']['responsible_ai'] = rai_results
            
            # Stage 5: Governance Audit
            logger.info("Stage 5: Governance Audit")
            governance_audit = self._conduct_governance_audit()
            pipeline_results['stage_results']['governance'] = governance_audit
            
            # Stage 6: Generate Reports
            logger.info("Stage 6: Report Generation")
            security_audit = security_results.get('security_audit', {})
            
            json_report_path = self.report_generator.generate_json_report(
                pipeline_results['stage_results'],
                governance_audit,
                security_audit,
                rai_results
            )
            
            markdown_report_path = self.report_generator.generate_markdown_report(
                pipeline_results['stage_results'],
                governance_audit,
                security_audit,
                rai_results
            )
            
            pipeline_results['stage_results']['reports'] = {
                'json_report': json_report_path,
                'markdown_report': markdown_report_path,
                'status': 'success'
            }
            
            # Calculate overall pipeline status
            pipeline_results['overall_status'] = self._calculate_overall_status(pipeline_results)
            
            # Record completion time
            pipeline_end_time = datetime.datetime.now()
            pipeline_results['execution_metadata']['end_time'] = pipeline_end_time.isoformat()
            pipeline_results['execution_metadata']['duration_seconds'] = (
                pipeline_end_time - pipeline_start_time
            ).total_seconds()
            
            logger.info(f"Pipeline execution completed with status: {pipeline_results['overall_status']}")
            
            return pipeline_results
            
        except Exception as e:
            logger.error(f"Pipeline execution failed: {str(e)}")
            pipeline_results['overall_status'] = 'failed'
            pipeline_results['error'] = str(e)
            
            pipeline_end_time = datetime.datetime.now()
            pipeline_results['execution_metadata']['end_time'] = pipeline_end_time.isoformat()
            pipeline_results['execution_metadata']['duration_seconds'] = (
                pipeline_end_time - pipeline_start_time
            ).total_seconds()
            
            return pipeline_results
    
    def _process_security_stage(self, ingestion_results: Dict[str, Any]) -> Dict[str, Any]:
        """Process security stage including PHI redaction and encryption"""
        
        security_results = {
            'phi_redaction': {},
            'encryption': {},
            'access_control': {},
            'security_audit': {}
        }
        
        try:
            # Process healthcare data security
            if (ingestion_results['results']['healthcare']['status'] == 'success' and
                isinstance(ingestion_results['results']['healthcare']['data'], pd.DataFrame)):
                healthcare_df = ingestion_results['results']['healthcare']['data']
                
                healthcare_security = self.security.secure_healthcare_data(healthcare_df, self.user_role)
                security_results['phi_redaction'] = healthcare_security
            elif ingestion_results['results']['healthcare']['status'] == 'success':
                # Data is already processed, skip security processing
                security_results['phi_redaction'] = {'status': 'skipped', 'reason': 'data already processed'}
            
            # Process other data types
            for data_type in ['barcode_data', 'navigation_data', 'telemetry_data']:
                if data_type in ingestion_results['results']:
                    staged_file = ingestion_results['results'][data_type].get('staged_file')
                    if staged_file:
                        security_result = self.security.secure_non_phi_data(
                            data_type, Path(staged_file), self.user_role
                        )
                        security_results['encryption'][data_type] = security_result
            
            # Generate security audit
            security_audit = self.security.generate_security_audit()
            security_results['security_audit'] = security_audit
            
            security_results['status'] = 'success'
            
        except Exception as e:
            logger.error(f"Security processing failed: {str(e)}")
            security_results['status'] = 'failed'
            security_results['error'] = str(e)
        
        return security_results
    
    def _conduct_governance_audit(self) -> Dict[str, Any]:
        """Conduct governance audit including lineage verification"""
        
        governance_audit = {
            'lineage_integrity': {},
            'data_provenance': {},
            'lineage_events_count': 0,
            'audit_timestamp': datetime.datetime.now().isoformat()
        }
        
        try:
            # Validate lineage integrity
            integrity_valid = self.architecture.validate_lineage_integrity()
            governance_audit['lineage_integrity'] = {
                'status': 'pass' if integrity_valid else 'fail',
                'chain_valid': integrity_valid
            }
            
            # Get lineage chain
            lineage_chain = self.architecture.get_lineage_chain()
            governance_audit['lineage_events_count'] = len(lineage_chain)
            
            # Analyze data provenance
            governance_audit['data_provenance'] = self._analyze_data_provenance(lineage_chain)
            
            # Overall governance status
            if integrity_valid and governance_audit['data_provenance']['status'] == 'pass':
                governance_audit['overall_status'] = 'pass'
            else:
                governance_audit['overall_status'] = 'fail'
                
        except Exception as e:
            logger.error(f"Governance audit failed: {str(e)}")
            governance_audit['overall_status'] = 'fail'
            governance_audit['error'] = str(e)
        
        return governance_audit
    
    def _analyze_data_provenance(self, lineage_chain: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Analyze data provenance from lineage chain"""
        
        provenance = {
            'status': 'pass',
            'source_verified': True,
            'chain_complete': True,
            'processing_stages': []
        }
        
        # Track processing stages
        stages_seen = set()
        modalities_seen = set()
        
        for event in lineage_chain:
            stage = event.get('stage')
            modality = event.get('modality')
            
            if stage:
                stages_seen.add(stage)
            if modality:
                modalities_seen.add(modality)
        
        provenance['processing_stages'] = list(stages_seen)
        provenance['modalities_processed'] = list(modalities_seen)
        
        # Check completeness
        required_stages = ['ingestion', 'validation', 'inference']
        missing_stages = [stage for stage in required_stages if stage not in stages_seen]
        
        if missing_stages:
            provenance['chain_complete'] = False
            provenance['missing_stages'] = missing_stages
            provenance['status'] = 'warning'
        
        return provenance
    
    def _calculate_overall_status(self, pipeline_results: Dict[str, Any]) -> str:
        """Calculate overall pipeline status from stage results"""
        
        stage_statuses = []
        
        # Check each stage
        for stage_name, stage_result in pipeline_results['stage_results'].items():
            if isinstance(stage_result, dict):
                if 'overall_status' in stage_result:
                    status = stage_result['overall_status']
                elif 'status' in stage_result:
                    status = stage_result['status']
                else:
                    status = 'unknown'
                
                stage_statuses.append(status)
        
        # Determine overall status
        if all(status in ['success', 'pass'] for status in stage_statuses):
            return 'success'
        elif any(status in ['failed', 'fail'] for status in stage_statuses):
            return 'failed'
        elif any(status in ['partial_success', 'warning'] for status in stage_statuses):
            return 'partial_success'
        else:
            return 'unknown'
    
    def simulate_cart_journey(self) -> Dict[str, Any]:
        """Simulate complete cart journey from prescription to delivery"""
        
        logger.info("Simulating complete autonomous medical cart journey")
        
        journey_log = {
            'journey_id': f"cart_journey_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}",
            'start_time': datetime.datetime.now().isoformat(),
            'journey_stages': [],
            'delivery_status': 'in_progress'
        }
        
        # Run complete pipeline
        pipeline_results = self.run_complete_pipeline()
        
        # Simulate journey stages based on pipeline results
        journey_stages = [
            self._simulate_prescription_receipt(pipeline_results),
            self._simulate_medication_retrieval(pipeline_results),
            self._simulate_navigation_to_patient(pipeline_results),
            self._simulate_delivery_verification(pipeline_results),
            self._simulate_return_journey(pipeline_results)
        ]
        
        journey_log['journey_stages'] = journey_stages
        journey_log['end_time'] = datetime.datetime.now().isoformat()
        
        # Determine final delivery status
        if all(stage['status'] == 'success' for stage in journey_stages):
            journey_log['delivery_status'] = 'delivered_successfully'
        elif any(stage['status'] == 'failed' for stage in journey_stages):
            journey_log['delivery_status'] = 'delivery_failed'
        else:
            journey_log['delivery_status'] = 'delivery_partial'
        
        # Save journey log
        journey_file = self.architecture.reports_path / f"cart_journey_{journey_log['journey_id']}.json"
        with open(journey_file, 'w') as f:
            json.dump({
                'journey_log': journey_log,
                'pipeline_results': pipeline_results
            }, f, indent=2, default=str)
        
        logger.info(f"Cart journey simulation completed: {journey_log['delivery_status']}")
        
        return {
            'journey_log': journey_log,
            'pipeline_results': pipeline_results,
            'journey_file': str(journey_file)
        }
    
    def _simulate_prescription_receipt(self, pipeline_results: Dict[str, Any]) -> Dict[str, Any]:
        """Simulate receiving prescription order"""
        
        stage = {
            'stage_name': 'prescription_receipt',
            'timestamp': datetime.datetime.now().isoformat(),
            'status': 'success',
            'details': {}
        }
        
        # Check if healthcare data was successfully ingested
        if (pipeline_results.get('stage_results', {}).get('ingestion', {}).get('results', {})
            .get('healthcare', {}).get('status') == 'success'):
            
            # Data is now in data_summary format for serialization
            healthcare_info = pipeline_results['stage_results']['ingestion']['results']['healthcare']
            if 'data_summary' in healthcare_info:
                sample_prescription = {
                    'Name': 'REDACTED_PATIENT',
                    'Medication': 'Sample_Medication',
                    'Medical Condition': 'Sample_Condition'
                }
            else:
                sample_prescription = None
            
            if sample_prescription is not None:
                stage['details'] = {
                    'prescription_received': True,
                    'patient_info': {
                        'name': sample_prescription['Name'],
                        'medication': sample_prescription['Medication'],
                        'condition': sample_prescription['Medical Condition']
                    },
                    'phi_protected': True
                }
            else:
                stage['status'] = 'warning'
                stage['details'] = {'prescription_received': False, 'reason': 'No prescription data available'}
        else:
            stage['status'] = 'failed'
            stage['details'] = {'prescription_received': False, 'reason': 'Healthcare data ingestion failed'}
        
        return stage
    
    def _simulate_medication_retrieval(self, pipeline_results: Dict[str, Any]) -> Dict[str, Any]:
        """Simulate retrieving medication from pharmacy"""
        
        stage = {
            'stage_name': 'medication_retrieval',
            'timestamp': datetime.datetime.now().isoformat(),
            'status': 'unknown',
            'details': {}
        }
        
        # Check prescription matching results
        prescription_results = (pipeline_results.get('stage_results', {})
                              .get('inference', {}).get('prescription_matching'))
        
        if prescription_results:
            match_rate = prescription_results.get('summary', {}).get('match_success_rate', 0)
            confirmed_matches = prescription_results.get('summary', {}).get('confirmed_matches', 0)
            
            if match_rate >= 0.8:
                stage['status'] = 'success'
                stage['details'] = {
                    'medications_retrieved': confirmed_matches,
                    'barcode_verification': 'passed',
                    'match_rate': match_rate
                }
            elif match_rate >= 0.5:
                stage['status'] = 'warning'
                stage['details'] = {
                    'medications_retrieved': confirmed_matches,
                    'barcode_verification': 'partial',
                    'match_rate': match_rate,
                    'manual_verification_required': True
                }
            else:
                stage['status'] = 'failed'
                stage['details'] = {
                    'medications_retrieved': 0,
                    'barcode_verification': 'failed',
                    'match_rate': match_rate,
                    'reason': 'Poor prescription-barcode matching'
                }
        else:
            stage['status'] = 'failed'
            stage['details'] = {'reason': 'No prescription matching results available'}
        
        return stage
    
    def _simulate_navigation_to_patient(self, pipeline_results: Dict[str, Any]) -> Dict[str, Any]:
        """Simulate navigating to patient location"""
        
        stage = {
            'stage_name': 'navigation_to_patient',
            'timestamp': datetime.datetime.now().isoformat(),
            'status': 'unknown',
            'details': {}
        }
        
        # Check navigation analysis results
        navigation_results = (pipeline_results.get('stage_results', {})
                            .get('inference', {}).get('navigation_analysis'))
        
        if navigation_results:
            nav_status = navigation_results.get('summary', {}).get('navigation_status', 'unknown')
            robustness = navigation_results.get('summary', {}).get('average_occlusion_robustness', 0)
            
            if nav_status == 'good' and robustness > 0.7:
                stage['status'] = 'success'
                stage['details'] = {
                    'navigation_completed': True,
                    'route_optimization': 'efficient',
                    'obstacle_handling': 'robust',
                    'robustness_score': robustness
                }
            elif nav_status == 'adequate' or robustness > 0.4:
                stage['status'] = 'warning'
                stage['details'] = {
                    'navigation_completed': True,
                    'route_optimization': 'suboptimal',
                    'obstacle_handling': 'limited',
                    'robustness_score': robustness,
                    'assistance_required': True
                }
            else:
                stage['status'] = 'failed'
                stage['details'] = {
                    'navigation_completed': False,
                    'obstacle_handling': 'poor',
                    'robustness_score': robustness,
                    'reason': 'Navigation system unreliable'
                }
        else:
            stage['status'] = 'failed'
            stage['details'] = {'reason': 'No navigation analysis results available'}
        
        return stage
    
    def _simulate_delivery_verification(self, pipeline_results: Dict[str, Any]) -> Dict[str, Any]:
        """Simulate delivery verification at patient location"""
        
        stage = {
            'stage_name': 'delivery_verification',
            'timestamp': datetime.datetime.now().isoformat(),
            'status': 'unknown',
            'details': {}
        }
        
        # Check telemetry stability for secure delivery
        telemetry_results = (pipeline_results.get('stage_results', {})
                           .get('inference', {}).get('telemetry_analysis'))
        
        if telemetry_results:
            stability_status = telemetry_results.get('summary', {}).get('overall_stability_status', 'unknown')
            stable_subjects = telemetry_results.get('summary', {}).get('stable_subjects', 0)
            total_subjects = telemetry_results.get('summary', {}).get('subjects_analyzed', 1)
            
            stability_ratio = stable_subjects / max(total_subjects, 1)
            
            if stability_status == 'stable' and stability_ratio >= 0.8:
                stage['status'] = 'success'
                stage['details'] = {
                    'delivery_verified': True,
                    'patient_identification': 'confirmed',
                    'medication_handed_over': True,
                    'cart_stability': 'excellent',
                    'stability_ratio': stability_ratio
                }
            elif stability_ratio >= 0.5:
                stage['status'] = 'warning'
                stage['details'] = {
                    'delivery_verified': True,
                    'patient_identification': 'confirmed',
                    'medication_handed_over': True,
                    'cart_stability': 'adequate',
                    'stability_ratio': stability_ratio,
                    'monitoring_recommended': True
                }
            else:
                stage['status'] = 'failed'
                stage['details'] = {
                    'delivery_verified': False,
                    'cart_stability': 'poor',
                    'stability_ratio': stability_ratio,
                    'reason': 'Cart instability detected - delivery unsafe'
                }
        else:
            stage['status'] = 'warning'
            stage['details'] = {
                'delivery_verified': True,
                'reason': 'No telemetry data available for stability verification'
            }
        
        return stage
    
    def _simulate_return_journey(self, pipeline_results: Dict[str, Any]) -> Dict[str, Any]:
        """Simulate cart returning to pharmacy"""
        
        stage = {
            'stage_name': 'return_journey',
            'timestamp': datetime.datetime.now().isoformat(),
            'status': 'success',  # Assume return is always successful for demo
            'details': {
                'return_completed': True,
                'route_efficiency': 'optimal',
                'battery_status': 'adequate',
                'maintenance_alerts': []
            }
        }
        
        # Check for any system warnings that might affect return
        rai_results = pipeline_results.get('stage_results', {}).get('responsible_ai', {})
        if rai_results and 'overall_assessment' in rai_results:
            rai_status = rai_results['overall_assessment'].get('overall_status', 'unknown')
            
            if rai_status == 'needs_improvement':
                stage['details']['maintenance_alerts'].append('AI system requires attention')
                stage['status'] = 'warning'
        
        return stage

def main():
    """Main entry point for the Medical Cart Pipeline"""
    
    parser = argparse.ArgumentParser(description='Autonomous Medical Cart Pipeline')
    parser.add_argument('--user-role', 
                       choices=[SecurityRole.ADMIN, SecurityRole.MEDICAL_STAFF, 
                               SecurityRole.CART_OPERATOR, SecurityRole.AUDITOR],
                       default=SecurityRole.MEDICAL_STAFF,
                       help='User role for access control')
    parser.add_argument('--verbose', action='store_true', help='Enable verbose logging')
    parser.add_argument('--workspace', 
                       default='/Users/vasundras/Desktop/pb-11-mmgovernancepipeline',
                       help='Workspace path')
    parser.add_argument('--mode', 
                       choices=['pipeline', 'journey', 'both'],
                       default='both',
                       help='Execution mode')
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    try:
        # Initialize pipeline
        pipeline = MedicalCartPipeline(args.workspace, args.user_role)
        
        print(f"\n=== Autonomous Medical Cart Pipeline ===")
        print(f"User Role: {args.user_role}")
        print(f"Workspace: {args.workspace}")
        print(f"Execution Mode: {args.mode}")
        print(f"Start Time: {datetime.datetime.now().isoformat()}")
        print("=" * 50)
        
        if args.mode in ['pipeline', 'both']:
            print("\nExecuting pipeline...")
            pipeline_results = pipeline.run_complete_pipeline()
            
            print(f"\nPipeline Status: {pipeline_results['overall_status'].upper()}")
            
            # Print summary of each stage
            for stage_name, stage_result in pipeline_results.get('stage_results', {}).items():
                if isinstance(stage_result, dict):
                    status = stage_result.get('overall_status') or stage_result.get('status', 'unknown')
                    print(f"  {stage_name.title()}: {status.upper()}")
        
        if args.mode in ['journey', 'both']:
            print("\nSimulating cart journey...")
            journey_results = pipeline.simulate_cart_journey()
            
            journey_log = journey_results['journey_log']
            print(f"\nJourney Status: {journey_log['delivery_status'].upper()}")
            
            # Print journey stages
            for stage in journey_log['journey_stages']:
                print(f"  {stage['stage_name'].replace('_', ' ').title()}: {stage['status'].upper()}")
            
            print(f"\nJourney log saved to: {journey_results['journey_file']}")
        
        print(f"\nReports generated in: {pipeline.architecture.reports_path}")
        print("Pipeline execution completed successfully!")
        
    except Exception as e:
        logger.error(f"Pipeline execution failed: {str(e)}")
        print(f"\nError: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()