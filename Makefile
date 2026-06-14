.PHONY: install build

install:
	pip install .

build:
	uv run nb build-ui
	pip install .
