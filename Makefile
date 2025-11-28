.PHONY: install build publish lint test integration_test coverage

install:
	poetry install

build:
	poetry build

publish:
	poetry publish -r rd-ai-common-artifacts

lint:
	@:

test:
	poetry run pytest tests

coverage:
	poetry run pytest --cov=outsystems tests --cov-config .coveragerc  --cov-report=html:coverage --cov-report=xml