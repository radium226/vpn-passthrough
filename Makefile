SHELL := bash
.SHELLFLAGS := -euEo pipefail -c

.ONESHELL:


.DEFAULT_GOAL := help


# Targets

##@ General
.PHONY: help
help: ## Display this message
	@ awk 'BEGIN {FS = ":.*##"; printf "\nUsage:\n  make \033[36m<target>\033[0m\n"} /^[a-zA-Z_0-9-]+:.*?##/ { printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2 } /^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) } ' $(MAKEFILE_LIST)



.PHONY: run
run: ## Run the application
	@ mise exec -- uv run vpn-passthrough


##@ Checks
.PHONY: check
check: ## Run all checks
	@ echo "Running all checks..." >&2
	@ $(MAKE) mypy
	@ $(MAKE) ruff
	@ $(MAKE) pytest
	@ echo "All checks passed!" >&2



.PHONY: mypy
mypy: ## Run mypy
	mise exec -- uv run mypy -p "radium226.vpn_passthrough"



.PHONY: ruff
ruff: ## Run ruff
	mise exec -- uv run ruff check "src/radium226/vpn_passthrough"



.PHONY: pytest
pytest: ## Run the tests using pytest
	mise exec -- uv run pytest -k "(not e2e) and (not sudo)"


.PHONY: pytest-e2e
pytest-e2e: ## Run end-to-end tests using pytest
	mise exec -- uv run pytest -k "e2e"


.PHONY: pytest-sudo
pytest-sudo: ## Run tests that require sudo privileges
	mise exec -- uv sync
	mise exec -- sudo -E sh -c 'source "./.venv/bin/activate" && pytest -k "sudo"'


.PHONY: reset
reset: ## Reset the environment
	sudo systemctl stop docker.service docker.socket
	sudo nft flush ruleset
	sudo sysctl -w net.ipv4.ip_forward=1
	sudo sysctl -w net.ipv6.conf.all.forwarding=1


.PHONY: start-server
start-server:
	mise exec -- sudo -E sh -c 'source "./.venv/bin/activate" && vpn-passthroughd'