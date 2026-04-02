## DB-first 動保園區資料平台規格（第一階段已落地）

### 產品目標
- 先把常被查詢的動物園區、收容所、救援機構建立成種子實體
- 優先從資料庫顯示既有摘要、證據卡與建議詢問
- 若資料不足或過舊，再補做即時搜尋與分析

### 使用者流程
1. 使用者輸入實體名稱
2. 前端先打 `/api/entities/{entity}/snapshot` 與 `/api/entities/{entity}/suggestions`
3. 若資料庫已有資料，先顯示摘要卡與建議詢問
4. 使用者送出搜尋後，後端先查相同問題的快取結果
5. 若命中快取，直接回傳 `mode=cached`
6. 若未命中，再走即時搜尋、分析、寫回 DB、更新 snapshot 與 suggestions

### 第一批種子實體（內建 watchlist）
- 台北市立動物園（木柵動物園）
- 新竹市立動物園
- 壽山動物園
- 頑皮世界野生動物園
- 六福村野生動物王國
- 台北市動物之家
- 新北市八里動物之家
- 高雄市燕巢動物保護關愛園區
- 臺南市動物之家灣裡站
- 社團法人台灣流浪動物救援協會
- 社團法人台灣之心愛護動物協會
- 社團法人流浪動物花園協會

### 內建問題分類
- 一般查核問題
- 動保法／法規風險問題
- 照護與飼養環境問題
- 收容／繁殖／救援問題
- 近期爭議與待查問題

### 已新增資料表
- `entity_watchlists`
  - 決定哪些實體要背景更新、優先序、更新頻率
- `entity_keywords`
  - 記錄 canonical name、alias、常見關鍵詞
- `entity_summary_snapshots`
  - 存每個實體在 `general` / `animal_law` 模式下的最新摘要與證據卡快照
- `entity_question_suggestions`
  - 存每個實體在不同模式下的建議詢問

### 已新增設定
- `bootstrap_seed_watchlist`
  - 啟用時自動把內建實體與 suggestions seed 進 DB
- `query_cache_ttl_hours`
  - 相同問題 DB-first 命中的時間窗
- `entity_snapshot_ttl_hours`
  - 預留給後續背景刷新與 UI 新鮮度判斷

### 已新增 API
- `GET /api/entities/{entity_name}/snapshot?animal_focus=true|false`
- `GET /api/entities/{entity_name}/suggestions?animal_focus=true|false`

### 搜尋 API 新流程
- `POST /api/search`
  - 先查 `search_queries + query_summaries + evidence_cards`
  - 若相同實體 + 相同問題 + 相同模式在 TTL 內已有結果，回傳 `mode=cached`
  - 否則執行 live search
  - 成功後寫回：
    - `search_queries`
    - `query_summaries`
    - `evidence_cards`
    - `entity_summary_snapshots`
    - `entity_question_suggestions`

### 前端已接上的能力
- 輸入實體名稱時，優先載入資料庫摘要卡
- 建議詢問會優先使用資料庫中的 suggestions
- 搜尋結果 mode 支援 `cached`
- 已支援 `/entities/{entityName}` 實體頁 deep link
- 實體頁可直接顯示 snapshot、suggestions、media 與近期查詢

### 這一階段刻意先不做
- 爆料直接公開
- 留言直接公開
- 強制 30 秒廣告
- 全量背景自動爬全網

### 下一步建議
1. 以 `backend/scripts/refresh_watchlist.py` 掛 `cron`，先做低頻背景刷新
2. 將 snapshot TTL 與 `最近更新` UI 接上
3. 新增留言與爆料的審核資料表與 workflow
4. 持續補強圖片 / 影片與實體頁的互動細節
5. 後續若 refresh 量變大，再升級成專用 worker / queue

### 背景 refresh CLI（已新增）
- `uv run python scripts/refresh_watchlist.py --limit 3`
- `uv run python scripts/refresh_watchlist.py --entity-name 台北市立動物園 --mode animal_law`

### 建議 cron 範例
- 每 12 小時跑一次：刷新前幾個 due watchlist
- 只刷新 `entity_watchlists` 中 `is_active=1` 且到期的實體
- 失敗時會記錄 `last_error_at`、`last_error_message`，並延後重試