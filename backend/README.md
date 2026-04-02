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

## Refresh built-in watchlist

可用 CLI 針對內建 watchlist 做背景 refresh，適合配 `cron`：

```bash
~/.local/bin/uv run python scripts/refresh_watchlist.py --limit 3
~/.local/bin/uv run python scripts/refresh_watchlist.py --entity-name 台北市立動物園 --mode animal_law
```

建議做法：

- 用 DB-first 顯示既有結果
- 每日或每 12 小時由 cron 跑一次 watchlist refresh
- 高成本的即時搜尋只在資料不足時再觸發

## Entity page routes

前端現在支援實體頁 deep link，可直接開：

```bash
http://localhost:9487/entities/%E5%8F%B0%E5%8C%97%E5%B8%82%E7%AB%8B%E5%8B%95%E7%89%A9%E5%9C%92
http://localhost:9487/entities/%E6%9C%A8%E6%9F%B5%E5%8B%95%E7%89%A9%E5%9C%92
```

實體頁會優先載入：

- snapshot 摘要
- suggestions 建議提問
- media 圖片 / 影片
- 最近查詢紀錄
