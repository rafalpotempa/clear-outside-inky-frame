.PHONY: compile-requirements install


regenerate-requirements:
	uv pip compile requirements/requirements.in -o requirements/requirements.txt
	uv pip compile requirements/requirements-stubs.in -o requirements/requirements-stubs.txt
	uv pip compile requirements/requirements-dev.in -o requirements/requirements-dev.txt

install:
	uv pip install -r requirements/requirements.txt
	uv pip install -r requirements/requirements-stubs.txt --target ./typings
	uv pip install -r requirements/requirements-dev.txt


test:
	pytest tests


test-full:
	pytest tests --live
