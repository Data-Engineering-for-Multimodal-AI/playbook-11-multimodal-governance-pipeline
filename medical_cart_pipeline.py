#!/usr/bin/env python3
"""
Medical Cart Pipeline - Main Orchestrator

Autonomous Medical Cart Multimodal Data Pipeline
Demonstrates end-to-end cart journey from prescription to delivery

Usage:
    python medical_cart_pipeline.py [--user-role ROLE] [--mode {pipeline,journey,both}] [--verbose]

Exit code: 0 when every check passes or only warns, 1 when a check fails.
"""

import argparse
import logging
import datetime
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Any, Optional

import pandas as pd

# Import pipeline modules
from pipeline_architecture import PipelineArchitecture, REPO_ROOT
from data_ingestion import DataIngestionModule, summarize
from security_module import SecurityModule, SecurityRole, normalize_identifier
from inference_module import InferenceModule
from responsible_ai import ResponsibleAIModule, worst
from report_generator import ReportGenerator

logger = logging.getLogger(__name__)

STATUS_LABEL = {'pass': 'PASS', 'warning': 'PASS WITH WARNINGS', 'fail': 'FAIL'}


def to_jsonable(obj: Any) -> Any:
    """Results without in-memory data (DataFrames, images), ready for JSON"""
    return json.loads(json.dumps(obj, default=lambda o: None if hasattr(o, 'shape') else str(o)))


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
        self.redacted_df: Optional[pd.DataFrame] = None

        logger.info(f"Medical Cart Pipeline initialized for user role: {user_role} (run {self.architecture.run_id})")

    def run_complete_pipeline(self) -> Dict[str, Any]:
        """Execute complete pipeline from ingestion to reporting"""

        logger.info("Starting complete Medical Cart Pipeline execution")
        pipeline_start_time = datetime.datetime.now()

        pipeline_results = {
            'execution_metadata': {
                'run_id': self.architecture.run_id,
                'start_time': pipeline_start_time.isoformat(),
                'user_role': self.user_role,
            },
            'stage_results': {},
            'overall_status': 'unknown'
        }

        try:
            # Stage 1: Data Ingestion
            logger.info("Stage 1: Data Ingestion")
            ingestion_results = self.ingestion.ingest_all_modalities()
            pipeline_results['stage_results']['ingestion'] = to_jsonable(summarize(ingestion_results))
            if ingestion_results['overall_status'] == 'failed':
                raise RuntimeError("Data ingestion failed - cannot proceed")

            # Stage 2: Security Processing
            logger.info("Stage 2: Security Processing")
            security_results = self._process_security_stage(ingestion_results)
            pipeline_results['stage_results']['security'] = to_jsonable(
                {k: v for k, v in security_results.items() if k != 'security_audit'})

            # Stage 3: Inference Processing (healthcare records only in redacted form)
            logger.info("Stage 3: Inference Processing")
            inference_results = self.inference.run_complete_inference(
                ingestion_results["results"], self.redacted_df, security_results["read_access"])
            self._stage_inference_outputs(inference_results)
            pipeline_results['stage_results']['inference'] = to_jsonable(inference_results)

            # Stage 4: Responsible AI Assessment
            logger.info("Stage 4: Responsible AI Assessment")
            rai_results = self.responsible_ai.run_responsible_ai_assessment(self.redacted_df, inference_results)
            pipeline_results['stage_results']['responsible_ai'] = to_jsonable(rai_results)

            # Stage 5: Governance Audit
            logger.info("Stage 5: Governance Audit")
            governance_audit = self._conduct_governance_audit(ingestion_results)
            pipeline_results['stage_results']['governance'] = governance_audit

            # The security audit covers everything the run did, so it comes last
            security_audit = self.security.generate_security_audit()
            pipeline_results['stage_results']['security']['security_audit'] = to_jsonable(security_audit)

            # One verdict for the console, the reports and the exit code
            verdict = self._build_verdict(pipeline_results['stage_results'], security_audit, governance_audit)
            pipeline_results['verdict'] = verdict
            pipeline_results['overall_status'] = verdict['overall_status']

            # Stage 6: Generate Reports
            logger.info("Stage 6: Report Generation")
            pipeline_results['stage_results']['reports'] = {
                'json_report': self.report_generator.generate_json_report(
                    pipeline_results['stage_results'], governance_audit, security_audit,
                    pipeline_results['stage_results']['responsible_ai'], verdict, self.architecture.run_id),
                'markdown_report': self.report_generator.generate_markdown_report(
                    pipeline_results['stage_results'], governance_audit, security_audit,
                    pipeline_results['stage_results']['responsible_ai'], verdict, self.architecture.run_id),
                'status': 'success'
            }

        except Exception as e:
            logger.exception(f"Pipeline execution failed: {e}")
            pipeline_results['overall_status'] = 'fail'
            pipeline_results['error'] = str(e)

        pipeline_end_time = datetime.datetime.now()
        pipeline_results['execution_metadata']['end_time'] = pipeline_end_time.isoformat()
        pipeline_results['execution_metadata']['duration_seconds'] = round(
            (pipeline_end_time - pipeline_start_time).total_seconds(), 1)
        logger.info(f"Pipeline execution finished with status: {pipeline_results['overall_status']}")
        return pipeline_results

    def _process_security_stage(self, ingestion_results: Dict[str, Any]) -> Dict[str, Any]:
        """PHI redaction and encryption of the records, screening of label payloads, access checks"""

        security_results = {'phi_redaction': {}, 'barcode_screening': {}, 'read_access': {}}

        healthcare = ingestion_results['results']['healthcare']
        if healthcare['status'] == 'success':
            phi = self.security.secure_healthcare_data(healthcare['data'], self.user_role)
            self.redacted_df = phi.pop('redacted_data', None)
            security_results['phi_redaction'] = phi
            # The raw records aren't needed past this point
            self._original_identifiers = set(pd.concat([healthcare['data']['Name'], healthcare['data']['Doctor']])
                                             .dropna().map(normalize_identifier))
            healthcare['data'] = None

        barcodes = ingestion_results['results']['barcodes']
        if barcodes['status'] == 'success':
            security_results['barcode_screening'] = self.security.screen_barcode_payloads(barcodes['data'], self.user_role)
            security_results['read_access']['barcode_data'] = security_results['barcode_screening']['status'] != 'denied'

        for data_type in ('navigation_data', 'telemetry_data'):
            security_results['read_access'][data_type] = self.security.authorize(self.user_role, 'read', data_type)

        security_results['status'] = ('failed' if security_results['phi_redaction'].get('status') == 'failed'
                                      else 'success')
        return security_results

    def _stage_inference_outputs(self, inference_results: Dict[str, Any]):
        """Stage the (non-PHI) inference outputs and keep encrypted copies where the role may write"""
        staged = self.architecture.staged_path
        outputs = {
            'barcode_data': ('barcode_verification.json', {
                'labels': (inference_results['prescription_matching'] or {}).get('label_results'),
                'robustness': inference_results['barcode_robustness']}),
            'navigation_data': ('navigation_decisions.json', inference_results['navigation_analysis']),
            'telemetry_data': ('motion_monitor.json', inference_results['telemetry_analysis']),
        }
        for data_type, (name, content) in outputs.items():
            if content is None:
                continue
            path = staged / name
            with open(path, 'w') as f:
                json.dump(to_jsonable(content), f, indent=2)
            self.security.secure_non_phi_data(data_type, path, self.user_role)

    def _conduct_governance_audit(self, ingestion_results: Dict[str, Any]) -> Dict[str, Any]:
        """Lineage verification, provenance of this run, and a scan for plaintext PHI on disk"""

        governance_audit = {
            'lineage_integrity': {},
            'data_provenance': {},
            'plaintext_phi_scan': {},
            'lineage_events_count': 0,
            'audit_timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat()
        }

        if not self.security.authorize(self.user_role, 'audit', 'governance'):
            governance_audit['overall_status'] = 'not_run'
            governance_audit['reason'] = f"role {self.user_role} may not run the governance audit"
            return governance_audit

        verification = self.architecture.verify_lineage()
        governance_audit['lineage_integrity'] = {
            'status': 'pass' if verification['valid'] else 'fail',
            'chain_valid': verification['valid'],
            **verification
        }
        run_events = self.architecture.get_lineage_chain(self.architecture.run_id)
        governance_audit['lineage_events_count'] = len(self.architecture.get_lineage_chain())
        governance_audit['run_events_count'] = len(run_events)
        governance_audit['data_provenance'] = self._analyze_data_provenance(run_events)
        governance_audit['plaintext_phi_scan'] = self._scan_for_plaintext_phi()

        statuses = [governance_audit['lineage_integrity']['status'], governance_audit['data_provenance']['status'],
                    governance_audit['plaintext_phi_scan']['status']]
        governance_audit['overall_status'] = worst(statuses)
        return governance_audit

    def _analyze_data_provenance(self, lineage_chain: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Did every modality go through the stages it should have, in this run?"""

        required = {
            'healthcare_csv': ['ingestion', 'phi_redaction', 'encryption'],
            'barcode_image': ['ingestion', 'phi_redaction', 'inference'],
            'video_frame': ['ingestion', 'inference'],
            'mhealth_telemetry': ['ingestion', 'inference'],
        }
        seen = {}
        for event in lineage_chain:
            seen.setdefault(event['modality'], set()).add(event['stage'])

        missing = {m: [s for s in stages if s not in seen.get(m, set())] for m, stages in required.items()}
        missing = {m: s for m, s in missing.items() if s}
        return {
            'status': 'pass' if not missing else 'warning',
            'stages_by_modality': {m: sorted(s) for m, s in seen.items()},
            'chain_complete': not missing,
            'missing_stages': missing,
        }

    def _scan_for_plaintext_phi(self) -> Dict[str, Any]:
        """Look for any patient or doctor name in the files this run left in plaintext"""
        names = getattr(self, '_original_identifiers', set())
        if not names:
            return {'status': 'warning', 'note': 'no records were read, nothing to look for'}
        lengths = sorted({len(n.split()) for n in names})
        candidates = [p for p in self.architecture.staged_path.rglob('*') if p.is_file() and p.suffix in ('.json', '.csv', '.txt')]
        candidates += [self.architecture.db_path, self.security.access_log_path]
        hits = {}
        for path in candidates:
            text = path.read_bytes().decode('latin-1').casefold()
            words = re.findall(r"[a-z.'-]+", text)
            found = {" ".join(words[i:i + n]) for n in lengths for i in range(len(words) - n + 1)} & names
            if found:
                hits[self.architecture.relative(path)] = len(found)
        return {'status': 'fail' if hits else 'pass', 'files_scanned': len(candidates),
                'names_looked_for': len(names), 'files_with_names': hits}

    def _build_verdict(self, stages: Dict[str, Any], security_audit: Dict[str, Any],
                       governance_audit: Dict[str, Any]) -> Dict[str, Any]:
        """Every check with its status and the reason, and the worst status overall"""
        checks = []

        def add(area, check, status, detail):
            checks.append({'area': area, 'check': check,
                           'status': {'not_run': 'warning'}.get(status, status), 'detail': detail})

        ingestion = stages['ingestion']
        failed = [m for m, r in ingestion['results'].items() if r['status'] != 'success']
        add('Ingestion', 'All four modalities read', 'pass' if not failed else 'fail',
            f"{ingestion['successful_modalities']}/{ingestion['total_modalities']} modalities"
            + (f"; failed: {', '.join(failed)}" if failed else ''))

        access = security_audit['access_control']
        add('Security', 'Access control', access['status'],
            f"{access['total_access_attempts']} decisions logged, {access['failed_access_attempts']} denied"
            + (f" ({'; '.join(access['denied'])})" if access['denied'] else ''))

        phi = security_audit['phi_protection']
        detail = phi['note']
        if phi.get('verification'):
            v, k = phi['verification'], phi['k_anonymity']
            detail = (f"{v['identifiers_checked']} patient, doctor and hospital names looked for, {v['residual_identifiers']} found; "
                      f"no contact details or exact dates")
        add('Security', 'PHI redaction verified', phi['status'], detail)
        if phi.get('k_anonymity'):
            k = phi['k_anonymity']
            add('Security', 'Re-identification risk (k-anonymity, k >= 5)', 'pass' if k['k'] >= 5 else 'warning',
                f"k={k['k']} over {', '.join(k['quasi_identifiers'])}; "
                f"{k['records_in_groups_under_5']} records in groups smaller than 5")

        screening = phi.get('barcode_screening')
        if screening:
            add('Security', 'Label payloads screened for personal data',
                'warning' if screening['quarantined'] else 'pass',
                f"{screening['quarantined']} of {screening['labels_screened']} labels carry personal data and were quarantined")

        enc = security_audit['encryption']
        add('Security', 'Encryption at rest', enc['status'],
            f"{enc['encrypted_files_count']} file(s) encrypted; {enc['note']}")

        if governance_audit.get('overall_status') == 'not_run':
            add('Governance', 'Governance audit', 'not_run', governance_audit['reason'])
        else:
            lineage = governance_audit['lineage_integrity']
            add('Governance', 'Lineage hash chain', lineage['status'],
                f"{lineage['events_checked']} events recomputed" if lineage['valid'] else
                f"event {lineage['first_bad_seq']}: {lineage['problem']}")
            prov = governance_audit['data_provenance']
            add('Governance', 'Provenance complete for this run', prov['status'],
                'every modality went through its stages' if prov['chain_complete'] else
                f"missing: {prov['missing_stages']}")
            scan = governance_audit['plaintext_phi_scan']
            add('Governance', 'No plaintext names on disk', scan['status'],
                f"{scan.get('files_scanned', 0)} files scanned" +
                (f"; names found in {scan['files_with_names']}" if scan.get('files_with_names') else ''))

        inference = stages['inference']
        matching = inference.get('prescription_matching')
        if matching:
            s = matching['summary']
            rate = s['match_success_rate']
            add('Inference', 'Prescriptions verifiable by label', 'pass' if rate >= 0.8 else 'warning' if rate >= 0.5 else 'fail',
                f"{s['prescriptions_auto_verified']} of {s['prescriptions']} ({rate:.1%}); "
                f"{s['confirmed_matches']} of {s['total_medications']} medications have a verified label")
        else:
            add('Inference', 'Prescriptions verifiable by label', 'not_run',
                inference['skipped'].get('prescription_matching', 'not run'))
        telemetry = inference.get('telemetry_analysis')
        if telemetry:
            s = telemetry['summary']
            status = {'stable': 'pass', 'moderately_stable': 'warning'}.get(s['overall_stability_status'], 'fail')
            add('Inference', 'Motion monitor on held-out subjects', status,
                f"balanced accuracy {s['test_balanced_accuracy']:.3f} on subjects {', '.join(s['test_subjects'])}")
        else:
            add('Inference', 'Motion monitor on held-out subjects', 'not_run',
                inference['skipped'].get('telemetry_analysis', 'not run'))

        rai = stages['responsible_ai']['overall_assessment']
        for check, status in rai['checks'].items():
            add('Responsible AI', check.replace('_', ' ').capitalize(), status, self._rai_detail(check, stages))

        overall = worst(c['status'] for c in checks)
        return {
            'overall_status': overall,
            'label': STATUS_LABEL[overall],
            'checks': checks,
            'counts': {s: sum(c['status'] == s for c in checks) for s in ('pass', 'warning', 'fail')},
        }

    @staticmethod
    def _rai_detail(check: str, stages: Dict[str, Any]) -> str:
        rai = stages['responsible_ai']
        if check == 'fairness_across_patient_groups':
            bias = rai['bias_analysis'].get('demographic_bias', {})
            if bias.get('bias_status') in (None, 'not_run'):
                return 'not run (no redacted records)'
            return (f"largest gap in auto-verification between groups {bias['overall_bias_score']:.1%}, "
                    f"lowest ratio {bias['min_disparate_impact_ratio']:.3f}")
        if check.startswith('fairness_across_people'):
            d = rai['bias_analysis']['subject_disparity']
            return f"accuracy gap between subjects {d['accuracy_gap']:.3f}" if 'accuracy_gap' in d else 'not run'
        robustness = rai['robustness_analysis']
        if check == 'navigation_robustness':
            r = robustness['occlusion_robustness']
            return (f"same decision in {r['overall_robustness']:.0%} of degraded views; "
                    f"{r['missed_yields']} missed yields") if 'overall_robustness' in r else 'not run'
        if check == 'label_robustness':
            r = robustness['label_robustness']
            return (f"labels decoded in {r['overall_decode_rate']:.0%} of degraded scans"
                    if 'overall_decode_rate' in r else 'not run')
        if check == 'sensor_robustness':
            r = robustness['sensor_robustness']
            return (f"worst balanced accuracy with a degraded sensor {r['degradation_robustness']:.3f}"
                    if 'degradation_robustness' in r else 'not run')
        return ''

    def simulate_cart_journey(self, pipeline_results: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Simulate complete cart journey from prescription to delivery, from the pipeline's results"""

        logger.info("Simulating complete autonomous medical cart journey")
        if pipeline_results is None:
            pipeline_results = self.run_complete_pipeline()

        journey_log = {
            'journey_id': f"cart_journey_{self.architecture.run_id}",
            'start_time': datetime.datetime.now().isoformat(),
            'journey_stages': [],
            'delivery_status': 'in_progress'
        }

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
            journey_log['delivery_status'] = 'delivered_with_warnings'

        # Save journey log
        journey_file = self.architecture.reports_path / f"{journey_log['journey_id']}.json"
        with open(journey_file, 'w') as f:
            json.dump({'journey_log': journey_log, 'pipeline_verdict': pipeline_results.get('verdict')},
                      f, indent=2, default=str)

        logger.info(f"Cart journey simulation completed: {journey_log['delivery_status']}")

        return {
            'journey_log': journey_log,
            'pipeline_results': pipeline_results,
            'journey_file': self.architecture.relative(journey_file)
        }

    def _inference(self, pipeline_results: Dict[str, Any], key: str) -> Optional[Dict[str, Any]]:
        return pipeline_results.get('stage_results', {}).get('inference', {}).get(key)

    def _simulate_prescription_receipt(self, pipeline_results: Dict[str, Any]) -> Dict[str, Any]:
        """Receive a prescription (the first redacted record: the cart never sees a name)"""

        stage = {
            'stage_name': 'prescription_receipt',
            'timestamp': datetime.datetime.now().isoformat(),
            'status': 'success',
            'details': {}
        }

        if self.redacted_df is not None and len(self.redacted_df):
            row = self.redacted_df.iloc[0]
            stage['details'] = {
                'prescription_received': True,
                'patient_info': {
                    'patient_id': row['Patient ID'],
                    'age_band': row['Age'],
                    'medication': row['Medication'],
                    'condition': row['Medical Condition']
                },
                'phi_protected': True
            }
        else:
            stage['status'] = 'failed'
            stage['details'] = {'prescription_received': False,
                                'reason': 'No redacted healthcare records (ingestion failed or access denied)'}

        return stage

    def _simulate_medication_retrieval(self, pipeline_results: Dict[str, Any]) -> Dict[str, Any]:
        """Retrieve the medication and confirm it by its label"""

        stage = {
            'stage_name': 'medication_retrieval',
            'timestamp': datetime.datetime.now().isoformat(),
            'status': 'unknown',
            'details': {}
        }

        prescription_results = self._inference(pipeline_results, 'prescription_matching')

        if prescription_results:
            summary = prescription_results['summary']
            match_rate = summary['match_success_rate']
            medication = self.redacted_df.iloc[0]['Medication'] if self.redacted_df is not None else None
            stage['details'] = {
                'this_prescription': medication,
                'this_prescription_verified_by_label': medication in prescription_results['auto_verified_medications'],
                'match_rate': round(match_rate, 4),
                'medications_with_verified_label': summary['confirmed_matches'],
                'labels_quarantined': summary['labels_quarantined'],
            }
            if match_rate >= 0.8:
                stage['status'] = 'success'
            elif match_rate >= 0.5:
                stage['status'] = 'warning'
                stage['details']['manual_verification_required_for'] = [
                    r['medication'] for r in prescription_results['matching_results'] if r['match_status'] != 'confirmed']
            else:
                stage['status'] = 'failed'
                stage['details']['reason'] = 'Too few prescriptions can be verified by label'
        else:
            stage['status'] = 'failed'
            stage['details'] = {'reason': 'No prescription matching results available'}

        return stage

    def _simulate_navigation_to_patient(self, pipeline_results: Dict[str, Any]) -> Dict[str, Any]:
        """Drive to the patient, yielding to people in the path"""

        stage = {
            'stage_name': 'navigation_to_patient',
            'timestamp': datetime.datetime.now().isoformat(),
            'status': 'unknown',
            'details': {}
        }

        navigation_results = self._inference(pipeline_results, 'navigation_analysis')

        if navigation_results:
            summary = navigation_results['summary']
            robustness = summary['average_occlusion_robustness']
            stage['details'] = {
                'frames_checked': summary['frames_processed'],
                'yields_for_people_in_path': summary['frames_with_people_in_path'],
                'robustness_score': round(robustness, 3),
                'missed_yields_when_view_degraded': summary['missed_yields_under_stress'],
            }
            if robustness >= 0.7 and not summary['missed_yields_under_stress']:
                stage['status'] = 'success'
            elif robustness >= 0.4:
                stage['status'] = 'warning'
                stage['details']['assistance_required'] = 'slow down when the camera view is degraded'
            else:
                stage['status'] = 'failed'
                stage['details']['reason'] = 'Navigation system unreliable'
        else:
            stage['status'] = 'failed'
            stage['details'] = {'reason': 'No navigation analysis results available'}

        return stage

    def _simulate_delivery_verification(self, pipeline_results: Dict[str, Any]) -> Dict[str, Any]:
        """Hand over only when the cart is still: the motion monitor must be reliable"""

        stage = {
            'stage_name': 'delivery_verification',
            'timestamp': datetime.datetime.now().isoformat(),
            'status': 'unknown',
            'details': {}
        }

        telemetry_results = self._inference(pipeline_results, 'telemetry_analysis')

        if telemetry_results and 'test_balanced_accuracy' in telemetry_results['summary']:
            summary = telemetry_results['summary']
            stage['details'] = {
                'motion_monitor_balanced_accuracy': summary['test_balanced_accuracy'],
                'worst_subject_accuracy': summary['worst_subject_accuracy'],
            }
            stage['status'] = {'stable': 'success', 'moderately_stable': 'warning'}.get(
                summary['overall_stability_status'], 'failed')
            if stage['status'] == 'failed':
                stage['details']['reason'] = 'Cart motion monitor unreliable - delivery unsafe'
        else:
            stage['status'] = 'warning'
            stage['details'] = {'reason': 'No telemetry available for stability verification'}

        return stage

    def _simulate_return_journey(self, pipeline_results: Dict[str, Any]) -> Dict[str, Any]:
        """Return to the pharmacy and raise what needs attention"""

        stage = {
            'stage_name': 'return_journey',
            'timestamp': datetime.datetime.now().isoformat(),
            'status': 'success',
            'details': {'return_completed': True, 'maintenance_alerts': []}
        }

        rai = pipeline_results.get('stage_results', {}).get('responsible_ai', {}).get('overall_assessment', {})
        if rai.get('overall_status') in ('warning', 'fail'):
            stage['details']['maintenance_alerts'] = rai.get('recommendations', [])
            stage['status'] = 'warning'

        return stage


def print_verdict(verdict: Dict[str, Any]):
    marks = {'pass': 'PASS', 'warning': 'WARN', 'fail': 'FAIL'}
    for check in verdict['checks']:
        print(f"  [{marks[check['status']]}] {check['area']}: {check['check']} - {check['detail']}")


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
                        default=str(REPO_ROOT),
                        help='Folder with sample-data/; outputs are written there (default: this folder)')
    parser.add_argument('--mode',
                        choices=['pipeline', 'journey', 'both'],
                        default='both',
                        help='Execution mode')

    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format='%(asctime)s - %(levelname)s - %(module)s - %(message)s')

    try:
        # Initialize pipeline
        pipeline = MedicalCartPipeline(args.workspace, args.user_role)
    except FileNotFoundError as e:
        print(f"\nError: {e}")
        sys.exit(1)

    print("\n=== Autonomous Medical Cart Pipeline ===")
    print(f"User Role: {args.user_role}")
    print(f"Workspace: {pipeline.architecture.workspace_path}")
    print(f"Execution Mode: {args.mode}")
    print(f"Run: {pipeline.architecture.run_id}")
    print("=" * 50)

    pipeline_results = pipeline.run_complete_pipeline()

    if args.mode in ['pipeline', 'both']:
        print(f"\nPipeline Status: {STATUS_LABEL.get(pipeline_results['overall_status'], 'FAIL')}")
        if 'verdict' in pipeline_results:
            print_verdict(pipeline_results['verdict'])

    if args.mode in ['journey', 'both'] and 'verdict' in pipeline_results:
        journey_results = pipeline.simulate_cart_journey(pipeline_results)
        journey_log = journey_results['journey_log']
        print(f"\nJourney Status: {journey_log['delivery_status'].upper()}")
        for stage in journey_log['journey_stages']:
            print(f"  {stage['stage_name'].replace('_', ' ').title()}: {stage['status'].upper()}")
        print(f"\nJourney log saved to: {journey_results['journey_file']}")

    if 'error' in pipeline_results:
        print(f"\nError: {pipeline_results['error']}")
        sys.exit(1)

    reports = pipeline_results['stage_results']['reports']
    print(f"\nReports: {pipeline.architecture.relative(reports['markdown_report'])} "
          f"(and .json) in {pipeline.architecture.reports_path}")
    verdict = pipeline_results['verdict']
    print(f"Pipeline finished: {verdict['label']} "
          f"({verdict['counts']['pass']} passed, {verdict['counts']['warning']} warnings, {verdict['counts']['fail']} failed)")
    sys.exit(1 if verdict['overall_status'] == 'fail' else 0)


if __name__ == "__main__":
    main()
