.PHONY: build-ui build

build-ui:
	cd nb-ui && pnpm build

build: build-ui
	mkdir -p nb/static
	cp -r nb-ui/dist/* nb/static/
	pip install .
