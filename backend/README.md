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

## Import entity aliases

```bash
~/.local/bin/uv run python scripts/import_entity_aliases.py examples/entity_aliases.example.csv
```
