# Animal Welfare Verifier

Search-first reputation and evidence platform for animal-related organizations or individuals.

## Stack

- Frontend: React + Vite
- Backend: FastAPI
- Python environment: `uv`

## What this MVP does

- accepts an entity name and a targeted question
- expands the query into multiple evidence-focused search phrases
- searches the web with Firecrawl when configured
- supplements Taiwan forum reputation signals with PTT and other public evidence sources
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

## Public Deployment

這個專案現在支援由 FastAPI 直接提供前端正式版檔案，對外只需要公開一個服務入口。

### Build and Run

```bash
cd frontend
npm install
npm run build

cd ../backend
~/.local/bin/uv sync --extra llm --extra scrapers
PORT=9487 ~/.local/bin/uv run uvicorn app.main:app --host 0.0.0.0 --port 9487
```

或直接使用一鍵腳本：

```bash
./backend/scripts/start_public_server.sh
```

### What Becomes Public

- `http://<your-host>:9487/`：前端網站
- `http://<your-host>:9487/api/health`：健康檢查
- `http://<your-host>:9487/docs`：API 文件

### Required Network Setup

- 開放對外連線到你的 `PORT`，預設是 `9487`
- 若有反向代理或網域，將公開網址轉發到後端服務即可
- 生產環境建議透過 Nginx、Caddy 或雲平台的 HTTPS 功能提供 TLS

## API Keys

- `FIRECRAWL_API_KEY`: required for live web search
- `OPENAI_API_KEY`: optional for richer balanced summaries
- `SERPAPI_API_KEY`: optional for stronger Google Maps / Google Reviews results

## Suggested Service Ports

- Frontend: `3010`
- Backend: `8010`
