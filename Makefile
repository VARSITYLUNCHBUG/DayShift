# dl-mm-discord: every dev, test and deploy task. Run it on Linux, or inside the dev VM on Windows
# (scripts/dev-vm.ps1 makes one with Multipass). `make` alone lists the targets.

SHELL := /bin/bash
# No -u: multipass and SSH run bash with ~/.bashrc, which reads unset variables such as PS1.
.SHELLFLAGS := -e -o pipefail -c
.DEFAULT_GOAL := help
MAKEFLAGS += --no-print-directory

export DOCKER_BUILDKIT := 1
# The e2e suite writes test-results/ as you.
export DRAFTBOT_UID := $(shell id -u)
export DRAFTBOT_GID := $(shell id -g)

DEV := docker compose -p draftbot-dev -f compose.yaml -f compose.dev.yaml
TEST := docker compose -p draftbot-test -f compose.yaml -f compose.test.yaml
WAIT := --wait --wait-timeout 300
# Anything after the target for pytest, e.g. make test ARGS="tests/test_flow.py -k ready".
ARGS ?=
# Real-Discord dev stack: make dev REAL_DISCORD=1 (uses .env, no simulator, no seed).
REAL_DISCORD ?=
# The client inventory for the deploy targets: make site CLIENT=acme.
CLIENT ?= example
ANSIBLE := cd deploy/ansible && .venv/bin/ansible-playbook -i inventories/$(CLIENT)

ifeq ($(REAL_DISCORD),1)
DEV_ENV := DRAFTBOT_ENV_FILE=.env
DEV_PROFILE :=
else
DEV_ENV := DRAFTBOT_ENV_FILE=.env.dev
DEV_PROFILE := --profile sim
endif

.PHONY: help
help: ## List the targets
	@awk 'BEGIN {FS = ":.*## "} /^##@/ {printf "\n%s\n", substr($$0, 5)} /^[a-z0-9-]+:.*## / {printf "  %-14s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

##@ Setup
.PHONY: setup
setup: ## Install the Python tools and the git hooks on this machine (needs uv)
	uv sync --frozen
	uv run pre-commit install --install-hooks

.env.dev:
	cp .env.dev.example .env.dev

##@ Dev stack (the app against the Discord simulator, seeded from fixtures/dev)
.PHONY: dev dev-logs dev-stop dev-reset superuser shell
dev: .env.dev ## Build and start the dev stack, migrate and seed it, and print the URLs
	$(DEV_ENV) $(DEV) $(DEV_PROFILE) build
ifneq ($(REAL_DISCORD),1)
	$(DEV_ENV) $(DEV) $(DEV_PROFILE) up -d $(WAIT) db discord-sim
	$(DEV_ENV) $(DEV) $(DEV_PROFILE) run --rm migrate sh -c \
		"python manage.py migrate --noinput && python manage.py load_presets && python manage.py dev_seed"
	$(DEV_ENV) $(DEV) $(DEV_PROFILE) up -d $(WAIT) --remove-orphans
else
	@test -f .env || { echo "Copy .env.example to .env and set DISCORD_TOKEN and DISCORD_GUILD_ID."; exit 1; }
	$(DEV_ENV) $(DEV) up -d $(WAIT) --remove-orphans db migrate web bot edge
endif
	@echo
	@echo "  Admin           http://localhost:$${DEV_EDGE_PORT:-18080}/admin/   (make superuser)"
	@echo "  Control panel   http://localhost:$${DEV_PANEL_PORT:-18091}"
	@echo "  Dev control API http://localhost:$${DEV_WEB_PORT:-18000}/_control/api/"
	@echo "  Discord sim     http://localhost:$${DEV_SIM_PORT:-18090}/_sim/state"
	@echo "  Postgres        127.0.0.1:$${DEV_DB_PORT:-15432} (draftbot / dev)"

dev-logs: ## Follow the dev stack's logs
	$(DEV_ENV) $(DEV) $(DEV_PROFILE) logs -f --tail 50

dev-stop: ## Stop the dev stack, keeping its data
	$(DEV_ENV) $(DEV) --profile sim stop

dev-reset: ## Drop the dev database and start again from the fixtures
	$(DEV_ENV) $(DEV) --profile sim down -v --remove-orphans
	$(MAKE) dev

superuser: ## Create an admin login on the dev stack
	$(DEV_ENV) $(DEV) exec web python manage.py createsuperuser

shell: ## A Django shell on the dev stack
	$(DEV_ENV) $(DEV) exec web python manage.py shell

##@ Checks and tests
.PHONY: check test test-fresh e2e ci
check: ## Every pre-commit hook over the whole tree: lint, format, types, fixtures, compose, Ansible
	uv run pre-commit run --all-files

test: ## The unit suite in Docker: cached image layers, the test databases kept between runs
	$(TEST) --profile unit build tests
	$(TEST) up -d $(WAIT) db
	$(TEST) --profile unit run --rm tests pytest -n auto --reuse-db $(ARGS)

test-fresh: ## The unit suite on new test databases (after editing a migration)
	$(TEST) down -v
	$(MAKE) test

e2e: ## The browser suite against the whole stack and the simulator
	mkdir -p test-results/e2e
	$(TEST) --profile e2e up -d --build $(WAIT) chrome control-panel bot
	$(TEST) --profile e2e run --rm --no-deps --build e2e pytest $(ARGS) \
		|| { $(TEST) --profile e2e logs --no-color --tail 40 web bot discord-sim; \
		     echo "Traces and screenshots: test-results/e2e/"; $(TEST) --profile '*' down -v; exit 1; }
	$(TEST) --profile '*' down -v --remove-orphans

ci: check test ## What CI runs: the checks, then the unit suite

.PHONY: sim-test panel-test
sim-test: ## The Discord simulator's own suite and types
	cd services/discord-sim && uv run --frozen pytest -q && uv run --frozen mypy

panel-test: ## The control panel's types, lint, tests and build, in a Node container
	docker run --rm -v "$(CURDIR)/services/control-panel:/src:ro" -w /work node:26.13.0-trixie-slim \
		sh -c "cp -r /src/. . && npm ci --no-audit --no-fund && npm run typecheck && npm run lint && npm test && npm run build"

.PHONY: compose-check
compose-check: ## Check every way the compose files combine (a pre-commit hook)
	@for files in "-f compose.yaml" "-f compose.yaml -f compose.dev.yaml" \
		"-f compose.yaml -f compose.test.yaml" "-f compose.yaml -f deploy/compose.prod.yaml"; do \
		DRAFTBOT_IMAGE_TAG=check EDGE_SITE=play.example.com \
			docker compose --env-file .env.example $$files --profile '*' config --quiet; \
	done

##@ Cleanup
.PHONY: clean
clean: ## Remove every container, volume, network and local image the dev and test stacks made
	-$(DEV) --profile '*' down -v --remove-orphans --rmi local
	-$(TEST) --profile '*' down -v --remove-orphans --rmi local
	@# Anything left by a run that was killed, or by an older compose file.
	@for project in draftbot-dev draftbot-test; do \
		docker ps -aq --filter label=com.docker.compose.project=$$project | xargs -r docker rm -f; \
		docker volume ls -q --filter label=com.docker.compose.project=$$project | xargs -r docker volume rm; \
		docker network ls -q --filter label=com.docker.compose.project=$$project | xargs -r docker network rm; \
	done
	rm -rf test-results .pytest_cache .hypothesis .mypy_cache .ruff_cache

##@ Deploy (Ansible; inventories/<CLIENT>, see deploy/README.md)
.PHONY: deploy-tools site deploy backup
deploy-tools: ## Install Ansible and its collections into deploy/ansible/.venv
	cd deploy/ansible && uv venv --allow-existing .venv && uv pip install --python .venv -r requirements.txt
	cd deploy/ansible && .venv/bin/ansible-galaxy collection install -r requirements.yml

site: ## Install or update a server: make site CLIENT=acme
	$(ANSIBLE) site.yml --ask-vault-pass

deploy: ## Upgrade a server to an image: make deploy CLIENT=acme TAG=sha-1234567
	@test -n "$(TAG)" || { echo "Set TAG, e.g. TAG=sha-1234567"; exit 1; }
	$(ANSIBLE) deploy.yml --ask-vault-pass -e draftbot_image_tag=$(TAG)

backup: ## Back up a server's database and fetch the dump: make backup CLIENT=acme
	$(ANSIBLE) backup.yml --ask-vault-pass
