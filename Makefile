# Targets are added as each Day 1 part lands (acme: part 3; oracle/run/bench: later days).
SEED ?= base
NOW ?= 2026-10-07T10:30:00+05:30

.PHONY: acme reset pdfs test test-e2e oracle ui adversarial bench

acme:  ## (export ACME_ADMIN_TOKEN first to enable /__admin/*; unset = closed) make sure the PDFs exist, reset to SEED at NOW, then serve Acme on http://localhost:8000 (one worker: SQLite + logical clock)
	uv run python -m acme.pdfs
	uv run python -m acme.seed --seed $(SEED) --now $(NOW)
	uv run uvicorn --factory acme.app:create_app --host 127.0.0.1 --port 8000

reset:  ## regenerate missing PDFs (warns on drift, never overwrites), rebuild acme.db for SEED (base | t8 | t9) at NOW; prints the state hash
	uv run python -m acme.pdfs
	uv run python -m acme.seed --seed $(SEED) --now $(NOW)

test:  ## fast: unit, integration and checker tests (no browser, no running server)
	uv run pytest -q -m "not e2e"

pdfs:  ## regenerate EVERY PDF and the manifest (only after an intended change to acme/pdfs.py or the seed facts)
	uv run python -m acme.pdfs --rewrite

test-e2e:  ## slow: Playwright and oracle runs (first tests arrive on Day 2; "none collected" is not a failure)
	@uv run pytest -q -m e2e; rc=$$?; \
	if [ $$rc -eq 5 ]; then echo "no e2e tests collected yet"; exit 0; fi; exit $$rc

oracle:  ## TASK=T1..T9|all [CHANNEL=gui] [CHAOS=profile CHAOS_SEED=0] [LIVE=1] [EVENTS=1] [HEADED=1]: reset, chaos, oracle via the scripted agent, checker (in-process Acme on a temp DB unless LIVE=1)
	uv run python -m bench.run_oracle $(TASK) $(if $(CHAOS),--chaos $(CHAOS) --chaos-seed $(or $(CHAOS_SEED),0)) $(if $(LIVE),--live) $(if $(EVENTS),--events) $(if $(CHANNEL),--channel $(CHANNEL))

ui:  ## the action-approval inbox on http://127.0.0.1:8100 over runs/runs.db (approve or reject held calls)
	uv run uvicorn --factory ui.app:create_app --host 127.0.0.1 --port 8100

adversarial:  ## every bench/adversarial script against an in-process Acme: each forbidden attempt must be stopped as expected
	uv run python -m bench.adversarial

bench:  ## [K=1] [ONLY=T1,T2] [NO_ADVERSARIAL=1]: AcmeBench in one command -> bench/results/<timestamp>.{json,md}
	uv run python -m bench.run_bench $(if $(K),--k $(K)) $(if $(ONLY),--only $(ONLY)) $(if $(NO_ADVERSARIAL),--no-adversarial)
