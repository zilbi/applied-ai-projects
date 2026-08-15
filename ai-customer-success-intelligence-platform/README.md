# AI Customer Success Intelligence Platform

Applied AI project for proactive customer success operations and AI-assisted portfolio management

## Overview

This project developed an end-to-end platform that helps Customer Success teams monitor client health, identify churn risks, organize daily work and generate evidence-based recommendations

The system combines a FastAPI backend, Telegram workflows, a Streamlit dashboard, PostgreSQL with vector search, background jobs and a context-grounded AI agent

## Scope of Work

The project included:

- client portfolio, task, calendar and interaction management
- health score and churn probability estimation
- explainable risk detection with recommended actions
- automatic task creation for high-priority risk events
- AI-assisted portfolio questions grounded in stored client context
- Telegram workflows for clients, risks, reports and voice input
- Streamlit dashboards for metrics, risks, tasks and success cases
- scheduled daily and weekly digests
- reusable report, email, call-script and objection-handling templates

## Repository Structure

- `src/api/` — FastAPI application and portfolio endpoints
- `src/bot/` — Telegram handlers, keyboards and response formatting
- `src/dashboard/` — Streamlit portfolio and risk dashboards
- `src/ai/` — AI agent, context building, voice and report generation
- `src/risk/` — health scoring, churn estimation and risk monitoring
- `src/organizer/` — tasks, calendar, notifications and daily planning
- `src/knowledge/` — success-case retrieval and industry benchmarks
- `src/workers/` — scheduled monitoring and digest jobs
- `templates/` — reports, client messages and operational scripts
- `scripts/` — setup, data generation and scheduled job entry points

<p align="center">
  <img src="materials/customer-success-platform-preview.svg" width="750">
</p>

<p align="center">
  <em>Preview of the AI Customer Success Intelligence Platform.</em>
</p>


## Materials

- [Configuration template](.env.example)
- [Local infrastructure](docker-compose.yml)
- [Communication templates](templates/)

## Status

Completed applied AI project
