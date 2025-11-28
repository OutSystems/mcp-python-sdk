.PHONY: install build publish lint test integration_test coverage

install:
	poetry install

build:
	poetry build

publish:
	poetry publish -r rd-ai-common-artifacts

lint:
	poetry run mypy --explicit-package-bases --namespace-packages outsystems/
	poetry run flake8

test:
	poetry run pytest tests

coverage:
	poetry run pytest --cov=outsystems tests --cov-config .coveragerc  --cov-report=html:coverage --cov-report=xml