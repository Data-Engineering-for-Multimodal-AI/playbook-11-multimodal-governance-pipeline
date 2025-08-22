# Autonomous Medical Cart Multimodal Pipeline

A comprehensive pipeline for Eighteen Labs' Autonomous Medical Cart that processes multimodal healthcare data through ingestion, governance, security, inference, and responsible AI stages.

## Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Usage](#usage)
- [Architecture](#architecture)
- [Data Sources](#data-sources)
- [Security Features](#security-features)
- [Governance & Audit](#governance--audit)
- [Responsible AI](#responsible-ai)
- [Output Structure](#output-structure)
- [Configuration](#configuration)
- [API Reference](#api-reference)
- [Contributing](#contributing)
- [License](#license)

## Overview

This pipeline demonstrates an end-to-end autonomous medical cart journey from prescription receipt to medication delivery, incorporating:

- **Multimodal Data Processing**: Healthcare records, barcode scanning, video navigation, and telemetry data
- **Governance & Lineage**: Immutable tracking with hash-chained events in SQLite
- **Security & Privacy**: PHI redaction, encryption, and role-based access control
- **AI Inference**: Prescription matching, navigation analysis, and stability monitoring
- **Responsible AI**: Bias detection, explainability, and robustness evaluation
- **Comprehensive Auditing**: JSON and Markdown reports with pass/fail results

## Features

### Core Capabilities
- **Multimodal Data Ingestion**: Process CSV, images, video, and sensor data
- **Data Governance**: Immutable lineage tracking with SQLite
- **Security Controls**: PHI redaction, AES encryption, role-based access
- **AI Inference**: TF-IDF matching, OpenCV analysis, telemetry processing
- **Bias Detection**: Demographic, route, and temporal bias analysis
- **Explainable AI**: Detailed failure explanations and root cause analysis
- **Audit Reports**: Comprehensive JSON and Markdown reporting

### Compliance Standards
- **HIPAA**: PHI detection, redaction, and audit logging
- **SOC 2**: Access controls, encryption, and monitoring
- **AI Ethics**: Bias detection, explainability, and fairness assessment
- **Medical Device**: Safety monitoring, reliability testing, and audit trails

## Installation

### Prerequisites

- Python 3.8 or higher
- Git
- 2GB+ disk space for sample data

### Setup Steps

1. **Clone the repository**
   ```bash
   git clone https://github.com/your-org/pb-11-mmgovernancepipeline.git
   cd pb-11-mmgovernancepipeline
   ```

2. **Create virtual environment** (recommended)
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Verify installation**
   ```bash
   python medical_cart_pipeline.py --help
   ```

### Dependencies

The project requires the following Python packages:
- `pandas>=1.5.0` - Data manipulation and analysis
- `scikit-learn>=1.0.0` - Machine learning algorithms
- `opencv-python-headless>=4.5.0` - Computer vision processing
- `cryptography>=3.4.0` - Encryption and security
- `Pillow>=8.0.0` - Image processing
- `pyzbar>=0.1.8` - Barcode decoding
- `numpy>=1.21.0` - Numerical computing
- `matplotlib>=3.5.0` - Data visualization
- `seaborn>=0.11.0` - Statistical visualization

## Quick Start

### Basic Usage

Run the complete pipeline with default settings:
```bash
python medical_cart_pipeline.py
```

### Common Commands

```bash
# Run with medical staff permissions
python medical_cart_pipeline.py --user-role medical_staff

# Run only the data processing pipeline
python medical_cart_pipeline.py --mode pipeline

# Run only the cart journey simulation
python medical_cart_pipeline.py --mode journey

# Enable detailed logging
python medical_cart_pipeline.py --verbose

# Run with administrator privileges
python medical_cart_pipeline.py --user-role admin --verbose
```

## Usage

### Command Line Interface

```bash
python medical_cart_pipeline.py [OPTIONS]

Options:
  --mode {pipeline,journey,both}  Execution mode (default: both)
  --user-role {admin,medical_staff,cart_operator,auditor}  User role (default: admin)
  --verbose                       Enable detailed logging
  --help                         Show help message
```

### Execution Modes

1. **Pipeline Mode**: Processes all data through ingestion, security, inference, and audit stages
2. **Journey Mode**: Simulates complete autonomous cart delivery journey
3. **Both Mode**: Runs pipeline processing followed by journey simulation

### User Roles

- **admin**: Full system access including encryption/decryption
- **medical_staff**: Healthcare data access with audit capabilities
- **cart_operator**: Navigation and telemetry data access
- **auditor**: Read-only access for compliance verification

## Architecture

### System Components

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│  Data Sources   │    │  Core Pipeline  │    │    Reports      │
├─────────────────┤    ├─────────────────┤    ├─────────────────┤
│ Healthcare CSV  │───▶│ Data Ingestion  │───▶│ JSON Reports    │
│ Barcode Images  │    │ Security Module │    │ Markdown Audit  │
│ Video Frames    │    │ Inference AI    │    │ Journey Logs    │
│ MHealth Sensors │    │ Responsible AI  │    │ Access Logs     │
└─────────────────┘    └─────────────────┘    └─────────────────┘
                              │
                       ┌─────────────────┐
                       │   Governance    │
                       │   Database      │
                       │  (SQLite +      │
                       │  Hash Chain)    │
                       └─────────────────┘
```

### Module Details

#### 1. Pipeline Architecture (`pipeline_architecture.py`)
- **Purpose**: Foundation layer providing database setup and lineage tracking
- **Key Features**:
  - SQLite governance database initialization
  - Hash-chained event recording for immutable audit trails
  - Modular component coordination
  - Data modality and processing stage management

#### 2. Data Ingestion (`data_ingestion.py`)
- **Purpose**: Load and validate multimodal data sources
- **Processes**:
  - Healthcare CSV: Loads 55K+ patient records with validation
  - Barcode Images: Extracts metadata from 6 barcode types
  - Video Processing: Extracts frames from navigation video
  - MHealth Data: Processes sensor telemetry from 10 subjects
- **Output**: Staged, validated data ready for processing

#### 3. Security Module (`security_module.py`)
- **Purpose**: Implement data protection and access controls
- **Features**:
  - PHI detection using regex patterns
  - AES encryption with PBKDF2 key derivation
  - Role-based access control matrix
  - Complete access logging and audit trails

#### 4. Inference Module (`inference_module.py`)
- **Purpose**: AI-powered analysis and matching
- **Capabilities**:
  - Prescription-to-barcode matching using TF-IDF similarity
  - Corridor navigation analysis with OpenCV
  - Robustness testing under occlusion conditions
  - Telemetry stability analysis for safety monitoring

#### 5. Responsible AI (`responsible_ai.py`)
- **Purpose**: Ensure ethical and robust AI behavior
- **Functions**:
  - Bias detection across demographics, routes, and time
  - Explainable AI for failure case analysis
  - Robustness evaluation under degraded conditions
  - Fairness assessment and recommendations

#### 6. Report Generator (`report_generator.py`)
- **Purpose**: Comprehensive audit and compliance reporting
- **Outputs**:
  - Detailed JSON reports with machine-readable results
  - Human-friendly Markdown summaries
  - Executive dashboards with key metrics
  - Pass/fail status tracking across all components

## Data Sources

All sample data is included in the `./sample-data/` directory:

### Healthcare Dataset (`healthcare_dataset.csv`)
- **Size**: 55,000+ patient records
- **Fields**: Patient demographics, prescriptions, medical conditions
- **Usage**: Prescription matching and bias detection
- **Privacy**: Contains synthetic PHI for redaction testing

### Barcode Images (`bar-codes/`)
- **Types**: QR Code, Code128, Code39, DataMatrix, EAN13, ITF
- **Format**: PNG images with embedded medication information
- **Usage**: Prescription-to-medication matching validation
- **Quality**: High-resolution test images for computer vision

### Video Data (`samples_data_vtest.avi`)
- **Content**: Corridor navigation footage
- **Usage**: Navigation analysis and robustness testing
- **Processing**: Frame extraction every 7 frames for analysis
- **Features**: Includes scenarios for occlusion testing

### MHealth Telemetry (`MHEALTHDATASET/`)
- **Subjects**: 10 individuals with sensor data
- **Sensors**: Accelerometer, gyroscope, magnetometer, ECG
- **Usage**: Cart stability and safety monitoring
- **Format**: Time-series CSV data with multiple sensor channels

## Security Features

### PHI Protection

The system implements comprehensive Protected Health Information (PHI) protection:

#### Detection Patterns
- **Names**: First and last name identification
- **Medical Conditions**: Disease and diagnosis recognition
- **Demographics**: Age, gender, and identifying information
- **Quasi-identifiers**: Combinations that could identify individuals

#### Redaction Methods
- **Name Pseudonymization**: Consistent hashing with salt
- **Condition Generalization**: Specific conditions mapped to categories
- **Age Binning**: Precise ages converted to ranges
- **Data Minimization**: Removal of unnecessary identifying fields

### Encryption

#### Data at Rest
- **Algorithm**: AES-128 via Fernet encryption
- **Key Derivation**: PBKDF2 with SHA-256
- **Salt Management**: Unique salts per encryption operation
- **File Integrity**: Verification checksums for encrypted data

#### Key Management
- **Password-based**: User-provided passwords for key derivation
- **Secure Storage**: Keys never stored in plaintext
- **Access Control**: Role-based key access permissions
- **Audit Trail**: Complete key usage logging

### Access Control

#### Role-Based Permissions

| Role | Healthcare Data | Barcode Data | Video Data | Telemetry | Encryption | Audit |
|------|----------------|--------------|------------|-----------|------------|-------|
| **admin** | Full | Full | Full | Full | Yes | Full |
| **medical_staff** | Read/Write | Read | Limited | Limited | No | Read |
| **cart_operator** | Limited | Full | Full | Full | No | Limited |
| **auditor** | Read-only | Read-only | Read-only | Read-only | No | Full |

#### Access Logging
- **Complete Tracking**: Every data access attempt logged
- **Metadata Capture**: User, timestamp, action, data type
- **Failure Recording**: Unauthorized access attempts documented
- **Audit Integration**: Logs integrated into compliance reports

## Governance & Audit

### Lineage Tracking

#### Immutable Event Chain
The system maintains a complete audit trail through hash-chained events:

```python
Event Structure:
- event_id: Unique identifier (UUID4)
- timestamp: ISO format with microsecond precision
- stage: Processing stage (ingestion, validation, encryption, etc.)
- modality: Data type (healthcare_csv, barcode_image, etc.)
- data_hash: SHA-256 hash of processed data
- previous_hash: Hash of previous event (creating chain)
- metadata: Processing-specific details
```

#### Chain Integrity
- **Hash Verification**: Each event references previous event hash
- **Tamper Detection**: Any modification breaks the chain
- **Complete Provenance**: Full data journey reconstruction
- **Audit Compliance**: Meets regulatory audit requirements

### Database Schema

#### Lineage Events Table
```sql
CREATE TABLE lineage_events (
    event_id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL,
    stage TEXT NOT NULL,
    modality TEXT NOT NULL,
    data_hash TEXT NOT NULL,
    previous_hash TEXT,
    metadata TEXT
);
```

#### Audit Queries
- **Chain Validation**: Verify hash chain integrity
- **Data Provenance**: Trace data from source to output
- **Processing History**: Complete transformation timeline
- **Compliance Reports**: Regulatory audit trail generation

## Responsible AI

### Bias Detection

#### Demographic Bias Analysis
- **Age Groups**: Delivery success rates across age ranges
- **Gender Analysis**: Service equality across gender identities
- **Medical Conditions**: Fair treatment regardless of diagnosis
- **Geographic Patterns**: Equal service across locations

#### Route Bias Detection
- **Path Selection**: Consistent navigation choices
- **Delivery Times**: Equal service times across routes
- **Accessibility**: Accommodation for mobility limitations
- **Priority Handling**: Fair emergency response protocols

#### Temporal Bias Analysis
- **Time of Day**: Consistent service across shifts
- **Day of Week**: Equal weekend and weekday service
- **Seasonal Patterns**: Service consistency over time
- **Load Balancing**: Fair resource allocation during peak times

### Explainable AI

#### Failure Analysis
The system provides detailed explanations for delivery failures:

```python
Explanation Categories:
- Prescription Matching: Why medication pairing failed
- Navigation Issues: Obstacle or path planning problems
- Stability Problems: Cart safety or balance concerns
- System Errors: Technical failure root causes
- Environmental Factors: External conditions affecting delivery
```

#### Root Cause Analysis
- **Multi-level Investigation**: Technical, procedural, and environmental factors
- **Evidence Collection**: Relevant data points and metrics
- **Impact Assessment**: Affected stakeholders and processes
- **Recommendation Generation**: Specific improvement suggestions

### Robustness Testing

#### Occlusion Tolerance
- **Central Obstruction**: 25% center area blocked
- **Side Obstruction**: 25% edge area blocked
- **Multiple Obstacles**: Combined obstruction scenarios
- **Dynamic Occlusion**: Moving obstacle simulation

#### Sensor Degradation
- **Missing Sensors**: Operation with reduced sensor input
- **Noisy Data**: Performance under signal interference
- **Calibration Drift**: Long-term accuracy maintenance
- **Failure Recovery**: Graceful degradation strategies

## Output Structure

The pipeline generates comprehensive outputs organized in the following structure:

```
project-root/
├── reports/                              # Generated audit reports
│   ├── audit_report_TIMESTAMP.json      # Machine-readable audit data
│   ├── audit_report_TIMESTAMP.md        # Human-readable summary
│   └── cart_journey_TIMESTAMP.json      # Detailed journey simulation
├── staged_data/                          # Processed data outputs
│   ├── healthcare_staged.csv            # Validated healthcare records
│   ├── barcode_metadata.json           # Barcode processing results
│   ├── video_frames_metadata.json      # Navigation analysis results
│   ├── mhealth_telemetry.json          # Telemetry stability data
│   ├── ingestion_summary.json          # Processing summary
│   └── secure/                         # Encrypted and redacted data
│       ├── healthcare_redacted.csv     # PHI-redacted healthcare data
│       └── healthcare_encrypted.csv    # AES-encrypted data files
├── governance.db                        # SQLite lineage database
├── access_log.json                     # Security access audit log
└── frame_*.png                         # Extracted video frames
```

### Report Contents

#### JSON Audit Report
```json
{
  "metadata": {
    "timestamp": "2025-01-XX...",
    "user_role": "medical_staff",
    "execution_mode": "both"
  },
  "pipeline_results": {
    "ingestion": {"status": "SUCCESS", "details": "..."},
    "security": {"status": "SUCCESS", "details": "..."},
    "inference": {"status": "SUCCESS", "details": "..."},
    "responsible_ai": {"status": "PASS_WITH_WARNINGS", "details": "..."}
  },
  "governance_audit": {
    "lineage_integrity": "VERIFIED",
    "event_count": 42,
    "hash_chain_valid": true
  },
  "journey_simulation": {
    "overall_status": "DELIVERED_SUCCESSFULLY",
    "stage_results": {...}
  }
}
```

#### Markdown Summary Report
- **Executive Summary**: High-level status and key findings
- **Component Assessment**: Detailed analysis of each module
- **Security Compliance**: PHI protection and access control verification
- **Responsible AI Assessment**: Bias detection and robustness results
- **Recommendations**: Specific improvement suggestions
- **Compliance Status**: Regulatory requirement verification

## Configuration

### Environment Variables

```bash
# Optional: Custom data directory
export MEDICAL_CART_DATA_DIR="/path/to/data"

# Optional: Custom output directory
export MEDICAL_CART_OUTPUT_DIR="/path/to/outputs"

# Optional: Encryption password (not recommended for production)
export MEDICAL_CART_ENCRYPTION_KEY="your-secure-password"
```

### Customization Options

#### Security Module Customization
```python
# Modify PHI detection patterns in security_module.py
PHI_PATTERNS = {
    'name': r'\b[A-Z][a-z]+\s+[A-Z][a-z]+\b',
    'condition': r'\b(diabetes|hypertension|asthma)\b',
    # Add organization-specific patterns
}
```

#### Inference Thresholds
```python
# Adjust matching sensitivity in inference_module.py
PRESCRIPTION_MATCH_THRESHOLD = 0.7  # 70% similarity required
NAVIGATION_CONFIDENCE_THRESHOLD = 0.8  # 80% confidence for navigation
```

#### Bias Detection Sensitivity
```python
# Configure bias detection in responsible_ai.py
BIAS_DETECTION_THRESHOLDS = {
    'demographic': 0.1,  # 10% difference triggers warning
    'route': 0.15,       # 15% difference for route bias
    'temporal': 0.2      # 20% difference for time-based bias
}
```

## API Reference

### Core Classes

#### PipelineArchitecture
```python
class PipelineArchitecture:
    def __init__(self, workspace_dir: str)
    def record_lineage_event(self, stage: ProcessingStage, 
                           modality: DataModality, 
                           data_hash: str, 
                           metadata: dict) -> str
    def validate_lineage_integrity(self) -> bool
```

#### DataIngestionModule
```python
class DataIngestionModule:
    def ingest_healthcare_data(self, filepath: str) -> dict
    def ingest_barcode_images(self, directory: str) -> dict
    def ingest_video_frames(self, filepath: str) -> dict
    def ingest_mhealth_data(self, directory: str) -> dict
```

#### SecurityModule
```python
class SecurityModule:
    def redact_phi(self, data: pd.DataFrame) -> pd.DataFrame
    def encrypt_file(self, filepath: str, password: str) -> str
    def check_access(self, user_role: SecurityRole, 
                    data_type: str, action: str) -> bool
```

### Utility Functions

#### Data Processing
```python
def validate_data_format(data: pd.DataFrame, expected_columns: list) -> bool
def calculate_data_hash(data: any) -> str
def extract_metadata(filepath: str) -> dict
```

#### Reporting
```python
def generate_executive_summary(results: dict) -> dict
def create_audit_report(pipeline_results: dict, format: str) -> str
def export_lineage_chain(output_file: str) -> bool
```

## Contributing

### Development Setup

1. **Fork the repository** and clone your fork
2. **Create a feature branch** from main
3. **Install development dependencies**:
   ```bash
   pip install -r requirements-dev.txt
   ```
4. **Run tests** to ensure everything works:
   ```bash
   python -m pytest tests/
   ```

### Code Standards

- **Python Style**: Follow PEP 8 guidelines
- **Documentation**: Comprehensive docstrings for all functions
- **Type Hints**: Use type annotations for function signatures
- **Error Handling**: Comprehensive exception handling
- **Logging**: Appropriate logging levels and messages

### Testing

- **Unit Tests**: Test individual functions and methods
- **Integration Tests**: Test module interactions
- **Security Tests**: Verify PHI protection and access controls
- **Performance Tests**: Ensure acceptable processing times

### Pull Request Process

1. **Update Documentation**: Ensure README and docstrings are current
2. **Add Tests**: Include tests for new functionality
3. **Security Review**: Verify no PHI leakage or security vulnerabilities
4. **Performance Check**: Ensure no significant performance degradation

## Troubleshooting

### Common Issues

#### Installation Problems
```bash
# OpenCV installation issues
pip install opencv-python-headless --no-cache-dir

# Barcode decoding issues
apt-get install libzbar0  # Ubuntu/Debian
brew install zbar         # macOS
```

#### Runtime Errors
```bash
# Permission errors with SQLite
chmod 755 .
chmod 644 governance.db

# Missing video files
ls -la sample-data/samples_data_vtest.avi
```

#### Performance Issues
- **Large Data Files**: Consider processing subsets for testing
- **Memory Usage**: Monitor RAM usage with large datasets
- **Disk Space**: Ensure sufficient space for frame extraction

### Support

For technical support:
1. **Check Documentation**: Review this README and inline code documentation
2. **Search Issues**: Look for similar problems in the issue tracker
3. **Create Issue**: Provide detailed error messages and system information
4. **Security Issues**: Report privately for security-related problems

## License

This project is licensed under the MIT License - see the LICENSE file for details.

### MIT License

Copyright (c) 2025 Data Engineering for Multimodal AI

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

---

**Note**: This is a prototype implementation for demonstration purposes. Production deployment requires additional security hardening, compliance validation, and regulatory approval.