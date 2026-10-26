.PHONY: smoke run pipeline journey verify tamper-demo clean

# Smoke tests on CPU with the committed sample data (about 30 s)
smoke:
	uv run pytest -q

# The full run: pipeline, then the cart journey (reports/ and staged_data/)
run:
	uv run python medical_cart_pipeline.py

pipeline:
	uv run python medical_cart_pipeline.py --mode pipeline

journey:
	uv run python medical_cart_pipeline.py --mode journey

# Recompute every hash in the lineage ledger, then watch it catch tampering on a copy
verify:
	uv run python verify_lineage.py

tamper-demo:
	uv run python verify_lineage.py --tamper-demo

clean:
	rm -rf reports staged_data governance.db access_log.json .pytest_cache
