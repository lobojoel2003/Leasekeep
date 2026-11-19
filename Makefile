.DEFAULT_GOAL := help
PYTHON ?= python

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-16s %s\n", $$1, $$2}'

install: ## Install runtime and development dependencies
	$(PYTHON) -m pip install -r requirements-dev.txt

demo: ## Create a database with the Riverbend demo data and start the dev server
	$(PYTHON) manage.py migrate
	$(PYTHON) manage.py seed_demo --with-users
	$(PYTHON) manage.py runserver

run: ## Start the development server
	$(PYTHON) manage.py runserver

test: ## Run the test suite with coverage
	$(PYTHON) -m pytest --cov

lint: ## Check style and formatting
	ruff check .
	ruff format --check .

format: ## Format the code
	ruff format .
	ruff check --fix .

migrations-check: ## Fail if models changed without a migration
	$(PYTHON) manage.py makemigrations --check --dry-run

screenshots: ## Regenerate README screenshots (needs `make demo` running and Playwright)
	node scripts/screenshots.mjs http://127.0.0.1:8000 docs/screenshots 2

docker: ## Build the Docker image locally
	docker build --build-arg VERSION=$$($(PYTHON) scripts/release_tools.py version) -t leasekeep:local .

release-check: ## Check that TAG (e.g. make release-check TAG=v1.0.0) matches the version and changelog
	$(PYTHON) scripts/release_tools.py check-tag $(TAG)

.PHONY: help install demo run test lint format migrations-check screenshots docker release-check
