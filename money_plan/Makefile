export COMPOSE_FILE := docker-compose.local.yml

# Extra arguments, e.g. `make manage ARGS="migrate"`
ARGS ?=

# Service used by `make bash`, e.g. `make bash SERVICE=postgres`
SERVICE ?= django

# Colors
CYAN   := \033[1;36m
GREEN  := \033[1;32m
YELLOW := \033[1;33m
RED    := \033[1;31m
RESET  := \033[0m

# say <color> <message>
say = @printf "$(1)%b$(RESET)\n" "$(2)"

.DEFAULT_GOAL := help
.PHONY: help build up start restart stop prune logs bash rebuild rebuild-node messages manage pytest

# help: List all available commands.
help:
	@printf "$(CYAN)💸 money_plan$(RESET) — available commands\n\n"
	@grep -E '^# [a-z-]+:' $(MAKEFILE_LIST) | \
		sed -E 's/^# ([a-z-]+): (.*)/\1\t\2/' | \
		awk -F'\t' '{ printf "  $(GREEN)%-14s$(RESET) %s\n", $$1, $$2 }'
	@printf "\n$(YELLOW)Tip:$(RESET) pass extra args with ARGS=\"...\"\n"

# build: Build python image.
build:
	$(call say,$(CYAN),🔨 Building python image...)
	@docker compose build $(ARGS)

# up: Start up containers.
up:
	$(call say,$(GREEN),🚀 Starting up containers...)
	@docker compose up -d --remove-orphans

# start: Start specific services, e.g. `make start ARGS="django postgres"`.
start:
	$(call say,$(GREEN),▶️  Starting $(or $(ARGS),all services)...)
	@docker compose up -d $(ARGS)

# restart: Restart all containers (or specific ones via ARGS).
restart:
	$(call say,$(YELLOW),🔄 Restarting $(or $(ARGS),all containers)...)
	@docker compose restart $(ARGS)

# stop: Stop containers.
stop:
	$(call say,$(YELLOW),🛑 Stopping containers...)
	@docker compose down

# prune: Remove containers and their volumes.
prune:
	$(call say,$(RED),🔥 Killing containers and removing volumes...)
	@docker compose down -v $(ARGS)

# logs: View container logs.
logs:
	$(call say,$(CYAN),📜 Following logs (Ctrl+C to exit)...)
	@docker compose logs -f $(ARGS)

# bash: Open a shell in a service container (default: django).
bash:
	$(call say,$(CYAN),🐚 Opening shell in $(SERVICE)...)
	@docker compose run --rm $(SERVICE) bash

# rebuild: Rebuild python image and reset its .venv volume (run after changing dependencies).
rebuild:
	$(call say,$(YELLOW),📦 Rebuilding python image and resetting .venv...)
	@docker compose build django
	@docker compose up -d -V --force-recreate django celeryworker celerybeat flower

# rebuild-node: Rebuild node image and reset its node_modules volume.
rebuild-node:
	$(call say,$(YELLOW),📦 Rebuilding node image and resetting node_modules...)
	@docker compose build node
	@docker compose up -d -V --force-recreate --no-deps node

# messages: Update the Thai .po file from the code, then compile it (restart django to pick it up).
messages:
	$(call say,$(CYAN),🌐 Updating and compiling translations...)
	@docker compose run --rm django python ./manage.py makemessages -l th --ignore=.venv --ignore=node_modules --ignore=staticfiles --no-location --no-wrap
	@docker compose run --rm django python ./manage.py compilemessages -l th

# manage: Executes `manage.py` command.
manage:
	$(call say,$(CYAN),⚙️  manage.py $(ARGS))
	@docker compose run --rm django python ./manage.py $(ARGS)

# pytest: Run tests with pytest.
pytest:
	$(call say,$(CYAN),🧪 Running tests...)
	@docker compose run --rm django pytest $(ARGS)
