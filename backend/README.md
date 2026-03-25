# Backend

FastAPI service for:

- expanding a user query
- searching the web
- extracting evidence cards
- generating a balanced summary

## Run

```bash
~/.local/bin/uv sync
~/.local/bin/uv run uvicorn app.main:app --reload
```

## Public Run

先建置前端，之後由 FastAPI 直接提供網站：

```bash
cd ../frontend
npm install
npm run build

cd ../backend
~/.local/bin/uv sync --extra llm --extra scrapers
PORT=9487 ~/.local/bin/uv run uvicorn app.main:app --host 0.0.0.0 --port 9487
```

也可以直接從專案根目錄執行：

```bash
./backend/scripts/start_public_server.sh
```

## Import entity aliases

```bash
~/.local/bin/uv run python scripts/import_entity_aliases.py examples/entity_aliases.example.csv
```
