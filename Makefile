.PHONY: install build publish lint test integration_test coverage

install:
	@echo "🏠 Install project"
	uv sync

build:
	@echo "🏠 Build project"
	uv build

publish:
	@echo "🏠 Publish project"
	uv publish --index rd-ai-common-artifacts

lint:
	@:

test: lint
	@echo "🏠 Run tests"
	uv run pytest tests --verbose

coverage:
	@echo "🏠 Run coverage"
	uv run coverage run -m pytest tests
	uv run coverage report
	uv run coverage html
	uv run coverage xml