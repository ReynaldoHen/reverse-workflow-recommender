# Reverse Workflow Platform — convenience targets

MODEL ?= dengcao/Qwen3-8B:Q5_K_M

.PHONY: help up down build logs pull-model ps clean health

help:
	@echo "make up          - build & start the whole stack"
	@echo "make pull-model  - pull the LLM model into Ollama (MODEL=$(MODEL))"
	@echo "make down        - stop the stack"
	@echo "make logs        - tail all logs"
	@echo "make ps          - show running services"
	@echo "make health      - curl both service health endpoints"
	@echo "make clean       - stop and remove volumes (DESTROYS DATA)"

up:
	docker compose up -d --build

build:
	docker compose build

down:
	docker compose down

logs:
	docker compose logs -f

ps:
	docker compose ps

pull-model:
	docker compose exec ollama ollama pull $(MODEL)

health:
	@echo "LLM service:"; curl -s http://localhost:8000/health || true; echo
	@echo "Orchestrator:"; curl -s http://localhost:5005/ || true; echo

clean:
	docker compose down -v
