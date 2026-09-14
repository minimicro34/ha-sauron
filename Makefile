PYTHON ?= python3.14

.PHONY: help compile format format-check lint test check clean

help:
	@echo "Available targets:"
	@echo "  compile       Compile Python sources"
	@echo "  format        Format the code with Ruff"
	@echo "  format-check  Verify formatting without modifying files"
	@echo "  lint          Run Ruff lint"
	@echo "  test          Run pytest with coverage"
	@echo "  check         Run the complete local validation"
	@echo "  clean         Remove Python cache files"

compile:
	$(PYTHON) -m compileall custom_components tests

format:
	ruff format .

format-check:
	ruff format --check .

lint:
	ruff check .

test:
	$(PYTHON) -m pytest --cov --cov-report=term-missing

check: compile lint test

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	find . -type d -name ".ruff_cache" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	find . -type f -name ".coverage" -delete
	find . -type f -name ".DS_Store" -delete
