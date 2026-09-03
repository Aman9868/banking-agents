.PHONY: test lint run clean

test:
	.venv/bin/pytest -v -s tests/

run:
	.venv/bin/uvicorn apps.api.main:app --reload --host 127.0.0.1 --port 8000

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

