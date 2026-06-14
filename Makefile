.PHONY: install build

build:
	uv run nb build-ui

install:
	uv sync --extra all --extra dev

