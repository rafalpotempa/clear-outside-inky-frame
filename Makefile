.PHONY: compile-requirements install


regenerate-requirements:
	uv pip compile requirements/requirements.in -o requirements/requirements.txt
	uv pip compile requirements/requirements-stubs.in -o requirements/requirements-stubs.txt

install:
	uv pip install -r requirements/requirements.txt
	uv pip install -r requirements/requirements-stubs.txt --target ./typings


test:
	pytest tests


test-live:
	pytest tests -m "live"
