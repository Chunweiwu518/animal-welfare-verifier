# Animal Welfare Verifier

Search-first reputation and evidence platform for animal-related organizations or individuals.

## Stack

- Frontend: React + Vite
- Backend: FastAPI
- Python environment: `uv`

## What this MVP does

- accepts an entity name and a targeted question
- expands the query into multiple search phrases
- searches the web with Tavily when configured
- falls back to mock evidence when no API key is present
- classifies evidence into supporting, opposing, or neutral cards
- generates a balanced summary with confidence and follow-up suggestions

## Local Setup

### Backend

```bash
cd backend
cp .env.example .env
~/.local/bin/uv sync
~/.local/bin/uv run uvicorn app.main:app --reload
```

### Frontend

```bash
cd frontend
cp .env.example .env
npm install
npm run dev
```

## API Keys

- `TAVILY_API_KEY`: required for live web search
- `OPENAI_API_KEY`: optional for richer balanced summaries

## Suggested Service Ports

- Frontend: `3010`
- Backend: `8010`
