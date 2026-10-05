# Targets are added as each Day 1 part lands (acme: part 3; oracle/run/bench: later days).
SEED ?= base
NOW ?= 2026-10-07T10:30:00+05:30

.PHONY: reset test

reset:  ## rebuild acme/data/acme.db for SEED (base | t8 | t9) at the frozen NOW; prints the state hash
	uv run python -m acme.seed --seed $(SEED) --now $(NOW)

test:
	uv run pytest -q
