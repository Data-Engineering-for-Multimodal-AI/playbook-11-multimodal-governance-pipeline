.PHONY: setup smoke run pipeline journey verify tamper-demo clean

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

pipeline:
	uv run --frozen python medical_cart_pipeline.py --mode pipeline

journey:
	uv run --frozen python medical_cart_pipeline.py --mode journey

# Recompute every hash in the lineage ledger, then watch it catch tampering on a copy
verify:
	uv run --frozen python verify_lineage.py

tamper-demo:
	uv run --frozen python verify_lineage.py --tamper-demo

# Remove generated files. The sample data in sample-data/ is kept.
clean:
	rm -rf reports staged_data governance.db access_log.json .pytest_cache
