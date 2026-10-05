# Targets are added as each Day 1 part lands (acme: part 3; oracle/run/bench: later days).
SEED ?= base
NOW ?= 2026-10-07T10:30:00+05:30

.PHONY: reset test test-e2e

reset:  ## rebuild acme/data/acme.db for SEED (base | t8 | t9) at the frozen NOW; prints the state hash
	uv run python -m acme.seed --seed $(SEED) --now $(NOW)

test:  ## fast: unit, integration and checker tests (no browser, no running server)
	uv run pytest -q -m "not e2e"

test-e2e:  ## slow: Playwright and oracle runs (first tests arrive on Day 2; "none collected" is not a failure)
	@uv run pytest -q -m e2e; rc=$$?; \
	if [ $$rc -eq 5 ]; then echo "no e2e tests collected yet"; exit 0; fi; exit $$rc
