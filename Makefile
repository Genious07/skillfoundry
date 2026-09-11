.PHONY: install build dev test
install:
	uv sync --frozen --extra dev --extra web
	cd apps/web && npm ci
build:
	cd apps/web && npm run build
dev: build
	uv run --frozen --extra web skillfoundry-web
test:
	uv run --frozen --extra dev --extra web pytest -q
	cd apps/web && npm test && npm run build
