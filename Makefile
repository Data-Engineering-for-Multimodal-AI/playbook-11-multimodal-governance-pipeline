.PHONY: setup smoke run pipeline journey verify tamper-demo clean check-data load try-k-anonymity try-fairness-skew try-sensor-noise

# A bare `make` runs the smoke test, as it did before the uniform targets were added.
.DEFAULT_GOAL := smoke

# Uniform targets for The Playbooks. The book's commands (pip install -r requirements.txt,
# python medical_cart_pipeline.py --mode pipeline --user-role medical_staff,
# python medical_cart_pipeline.py --mode journey --user-role medical_staff) still work as printed.

# Install the locked dependencies into .venv. The sample data is in the repository.
setup:
	uv sync --frozen

# Smoke tests on CPU with the committed sample data (about 30 s)
smoke:
	uv run --frozen pytest -q

# The full run: pipeline, then the cart journey (reports/ and staged_data/, both gitignored)
run: setup
	uv run --frozen python medical_cart_pipeline.py
	@echo "playbook-11-multimodal-governance-pipeline" > .playbook-done

pipeline:
	uv run --frozen python medical_cart_pipeline.py --mode pipeline

journey:
	uv run --frozen python medical_cart_pipeline.py --mode journey

# Recompute every hash in the lineage ledger, then watch it catch tampering on a copy
verify:
	uv run --frozen python verify_lineage.py

tamper-demo:
	uv run --frozen python verify_lineage.py --tamper-demo

# Your own patient records: healthcare_dataset.csv (and optionally formulary.csv and bar-codes/) in DIR.
# check-data checks them and writes nothing; load runs the pipeline on them in own_data/<DIR name>/.
#   make check-data DIR=my_records
#   make load DIR=my_records
check-data:
	@test -n "$(DIR)" || { echo "Usage: make check-data DIR=path/to/folder"; exit 2; }
	uv run --frozen python scripts/own_records.py --dir "$(DIR)" --check-only

load:
	@test -n "$(DIR)" || { echo "Usage: make load DIR=path/to/folder"; exit 2; }
	uv run --frozen python scripts/own_records.py --dir "$(DIR)"

# Try this: three measured experiments (see README, "Try this"). They write nothing.
try-k-anonymity: setup
	uv run --frozen python experiments/k_anonymity.py

try-fairness-skew: setup
	uv run --frozen python experiments/fairness_skew.py

try-sensor-noise: setup
	uv run --frozen python experiments/sensor_noise.py

# Remove generated files, and the workspaces make load built in own_data/. The sample data in
# sample-data/ is kept.
clean:
	rm -rf reports staged_data governance.db access_log.json .pytest_cache own_data
