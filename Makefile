.PHONY: install build

build:
	cd nb-ui && { [ -d node_modules ] || pnpm install; } && pnpm build
	rm -rf nb/static && cp -r nb-ui/dist nb/static

install:
	uv sync --extra all --extra dev
