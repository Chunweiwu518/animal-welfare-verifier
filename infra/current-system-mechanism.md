## Animal Welfare Verifier — Current System Mechanism

### 文件目的
這份文件描述目前系統已落地的實際機制，重點是搜尋流程、資料庫累積方式、背景 refresh、以及為了降低雜訊而加入的高品質來源回用規則。

### 系統定位
目前系統不是純即時搜尋，也不是純靜態資料庫。
它是 **DB-first + live supplement** 的混合模式：

1. 先讀資料庫
2. 資料不足才做 live web search
3. 新結果會再寫回資料庫，讓下次更容易直接命中

### 使用者搜尋主流程
當使用者送出 `POST /api/search` 時，後端流程如下：

1. 先判斷搜尋模式
   - `animal_focus=false` -> `general`
   - `animal_focus=true` -> `animal_law`
2. 先查 **exact query cache**
   - 條件：同 entity、同 question、同 search mode
   - 若 TTL 內命中，直接回 `mode=cached`
3. 若 exact query cache 沒命中
   - 進入 `SearchService.search(...)`
4. `SearchService` 先查 **entity-level cached sources + latest snapshot**
5. 若資料夠新、夠多，直接回 `mode=cached`
6. 若資料不足，才進 **live search**
7. live search 完成後，經過過濾、排序、分析
8. 結果寫回資料庫，供後續查詢重用

### DB-first 命中條件
目前 entity-level DB-first 會看幾個門檻：

- cached sources 至少 `4` 筆
- latest snapshot 的 source count 至少 `4` 筆
- snapshot 必須夠新
  - 一般問題：`72` 小時內
  - 最近 / 最新 / 近期 這類問題：`24` 小時內

若不符合以上條件，就 fallback 到 live search。

### 資料不足時的 live search
當 DB 不足時，系統才會啟動 live providers。現有流程大致為：

1. 根據 entity + question 自動擴展 queries
2. 呼叫搜尋 providers 抓公開網頁結果
3. 合併平台型來源與既有高品質 cached sources
4. 去重、補內容、標註 source type
5. 過濾低訊號與不相關結果
6. 排序高價值證據
7. 交給分析服務產出 summary 與 evidence cards
8. 寫回 DB

### Query expansion 機制
系統目前有 **自動 query expansion**，但不是多輪 agent 式改寫。
它會根據：

- entity 名稱
- 常見別名/關鍵詞
- question 內容
- `animal_focus` 模式

去產生多組搜尋字串，例如：

- 評價 / 心得 / 新聞 / 報導
- PTT / Dcard / Facebook / Instagram / Threads
- 募資 / 捐款 / 善款 / 財務 / 透明
- 爭議 / 質疑 / 聲明 / 道歉
- 動保 / 動保法 / 動物福利 / 照護 / 虐待 / 超收

### 資料庫如何累積
系統目前是「累積查詢歷史 + 去重更新來源」的模式。

#### 會累積的資料
- `search_queries`
  - 每次有效搜尋都會新增一筆查詢紀錄
- `evidence_cards`
  - 每次分析採信的證據卡都會保存
- `entity_summary_snapshots`
  - 若摘要/證據內容有變，會保留新的 snapshot 版本

#### 不會無限重複增加的資料
- `sources`
  - 以 `url` 為唯一鍵做 upsert
  - 同一個 URL 再次抓到時，會更新內容與時間，不會重複新增很多筆

### Snapshot 歷史規則
`entity_summary_snapshots` 不是簡單覆蓋最新值。
目前規則是：

- 如果新 summary/evidence 與既有 snapshot hash 不同 -> 新增新版本
- 如果內容相同 -> 更新既有 snapshot 的時間與 `latest_query_id`

因此系統會保留有變動的歷史，而不是每次整包覆蓋。

### 背景 refresh 機制
目前已有 `backend/scripts/refresh_watchlist.py` 與 watchlist refresh service。
背景 refresh 的行為是：

1. 只處理 watchlist 中到期的實體
2. 預設聚焦 **zoo** 類型實體
3. 每個 due entity 產生對應問題並執行搜尋
4. refresh 流程會強制 `force_live=True`
5. 也就是說，背景 refresh 不會只吃舊 DB，而是會真的去抓新資料
6. refresh 成功後更新 snapshot、suggestions、watchlist 狀態

### 目前的 watchlist 預設策略
內建 watchlist seed 目前預設只聚焦 zoo：

- 台北市立動物園
- 新竹市立動物園
- 壽山動物園
- 頑皮世界野生動物園
- 六福村野生動物王國

### 為什麼之前可能會覺得資料有點亂
即使系統已有低訊號過濾，`sources` 仍可能收進一些 raw search 結果。
若這些 raw-only 結果在後續查詢又被重用，就會讓回答看起來有擦邊雜訊。

### 已新增的降噪規則（重要）
目前 **DB-first 可重用來源** 已經收緊成：

- 同 entity
- 同 search mode
- 而且 **曾經進入 `evidence_cards`** 的來源

這代表：

- 單純被 `cache_raw_sources()` 存進 `sources` 的 raw-only 頁面
- 如果沒有被分析服務採信
- 之後 **不會再被 DB-first 優先重用**

這個規則可降低：

- 跟題目不夠貼的評論
- 只有擦邊提到 entity 的頁面
- 沒被採信的論壇/留言型雜訊

### 目前 log 可觀察的搜尋決策
後端 log 已加入這些訊息，方便觀察搜尋是否先走 DB：

- `exact_query_cache_hit`
- `exact_query_cache_miss`
- `entity_cache_decision`
- `entity_cache_fallback_live`
- `search_completed`

可以直接從 log 看出：

- 是否命中 exact query cache
- entity snapshot / cached sources 是否足夠
- 為什麼 fallback 到 live
- 最後回的是 `cached`、`live` 或 `mock`

### 一句話總結
目前系統的實際機制是：

**先用資料庫中已採信的高品質證據回答；只有當資料不足、過舊或問題太新時，才做 live search，並把新的高品質結果再累積回資料庫。**
