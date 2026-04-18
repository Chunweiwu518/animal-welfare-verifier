# 評論爬取計劃

> 最後更新：2026-04-16
> 測試環境：WSL2 Ubuntu + Playwright + httpx

---

## 第一階段：先做這 4 個（免費可用，已驗證）

### 1. PTT 推文

**抓什麼**：每篇文章底下的推/噓/箭頭（這才是真正的口碑）

**怎麼抓**：
1. 用 httpx 搜尋 7 個看板：pet, dog, cat, AnimalForest, AnimalRight, Gossiping, WomenTalk
2. 搜尋關鍵字 = entity 名稱 + 別名（例如「趙媽媽狗園」「趙媽媽」）
3. 進入每篇文章，解析 `div.push`：
   - `span.push-tag`：推 / 噓 / →（情緒判斷）
   - `span.push-userid`：誰說的
   - `span.push-content`：說了什麼
   - `span.push-ipdatetime`：什麼時候說的
4. 每則推文 = 一筆 review 存入 DB

**抓多少**：每板前 10 篇文章 × 每篇全部推文（不設上限，一篇可能 200+ 則）

**為什麼 PTT 最重要**：
- 台灣最大匿名論壇，敢講真話
- 推/噓/箭頭天生帶情緒標籤（正面/負面/中性）
- 免費、不需 API key、沒有 Cloudflare 擋
- 一篇熱門文的推文量就超過其他平台所有評論加起來

---

### 2. Google News 新聞

**抓什麼**：新聞報導本身（新聞就是「評論」— 記者調查、社論、讀者投書）

**怎麼抓**：
1. Google News RSS：`https://news.google.com/rss/search?q={entity}&hl=zh-TW&gl=TW`
2. 解析 XML feed → 取得標題、來源媒體、連結、發布日期
3. 可選：用 trafilatura 抓新聞全文

**抓多少**：每個 entity 前 50 篇新聞

**為什麼做這個**：
- 完全免費，Google News RSS 沒有限制
- 新聞報導有公信力，特別是調查報導、裁罰報導
- 測試結果一次就拿到 100 篇，量夠

---

### 3. Threads（Meta 旗下，類似 Twitter）

**抓什麼**：公開貼文 + 貼文底下的回覆

**怎麼抓**：
1. 先用 Exa API 搜尋 `site:threads.net "{entity}"` → 找到相關帳號和貼文 URL
2. 用 Playwright 訪問公開 profile 頁面（不需登入）
3. 取得貼文連結列表
4. 進入每篇貼文 → 用 `page.inner_text('body')` 取得原文 + 所有回覆
5. 解析文字分段，區分原文和回覆

**抓多少**：每個帳號前 20 篇貼文 + 每篇全部回覆

**為什麼做這個**：
- Threads 是少數不需登入就能用 Playwright 爬到回覆的社群平台
- 測試成功拿到 17 篇貼文 + 回覆內容
- 動物相關社群在 Threads 上很活躍

---

### 4. Google Maps 評論

**抓什麼**：Google Maps 商家頁面的用戶評論（星等 + 文字）

**怎麼抓**：
1. SerpApi `engine=google_maps` 搜尋地點 → 取得 `place_id`
2. SerpApi `engine=google_maps_reviews` 取得評論列表
3. 每則評論有：user_name、rating（1-5 星）、snippet（評論文字）

**抓多少**：每個地點全部評論（通常 20-200 則）

**費用**：SerpApi $50/月（5000 次搜尋），每個 entity 用 2 次（搜地點 + 拿評論）

**為什麼做這個**：
- Google Maps 評論是最直接的「去過的人」的真實回饋
- 帶星等評分，可以量化
- 機制已驗證正常，只是額度用完需要補充

---

## 第二階段：之後再做（有限制）

### Facebook — 為什麼只能拿到「部分」？

**測試結果**：用 Playwright 訪問 `m.facebook.com`（手機版），不登入可以看到公開粉絲頁的貼文摘要。

**問題在哪**：
- 只能看到貼文的**前幾行**（Facebook 會截斷，顯示「查看更多」）
- **完全看不到貼文底下的留言**（Facebook 需要登入才會載入留言）
- 滾動載入有限，大約只能看到最近 10-15 篇貼文
- 不登入的話，滾幾次就會跳出登入遮罩擋住整個畫面

**要完整爬 Facebook 留言，需要**：
1. 一個 Facebook 帳號
2. 從瀏覽器匯出 cookie 檔案
3. 用 `facebook-scraper` library 搭配 cookie 爬取
4. 風險：Meta 可能封號，建議用不重要的帳號

**結論**：不登入只能拿到粉絲頁基本資訊和貼文摘要，拿不到留言。等有 cookie 再做。

---

### Instagram — 為什麼只有「摘要」？

**問題在哪**：
- Instagram 2024 年起全面封鎖未登入的 API 存取（GraphQL API 回 403）
- Playwright 訪問任何 IG 頁面都會要求登入
- Instaloader（專門爬 IG 的 Python library）不登入也被 403 擋住
- 唯一能做的是用 Exa AI 搜尋 `site:instagram.com "entity"` 取得**搜尋引擎索引的摘要**

**摘要 vs 真正留言的差別**：
- 摘要：搜尋引擎看到的快照，通常只有貼文的前幾句話，沒有底下的留言
- 真正留言：每則用戶留言的完整內容、留言者、時間

**要完整爬 Instagram，需要**：
1. 一個拋棄式 IG 帳號（不要用主要帳號，會被封）
2. 用 Instaloader 登入後爬取
3. 風險：帳號被封、IP 被擋、Meta 法律風險

**結論**：不登入只能拿到搜尋引擎摘要。真正的留言需要帳號。

---

### Dcard — 為什麼爬不了？

**Dcard 確實有公開 API**，而且 API 設計很友善：
```
搜尋文章：GET https://www.dcard.tw/service/api/v2/search/posts?query=狗園
取得留言：GET https://www.dcard.tw/service/api/v2/posts/{id}/comments?limit=100
```

**問題不是 API，是 Cloudflare**：
- Dcard 在 API 前面架了 Cloudflare 防護（Bot Fight Mode）
- 所有來自 server / 雲端 IP 的請求都被判定為機器人，直接 403
- 我們測試了 4 種方式全部被擋：
  1. httpx 直接呼叫 → 403
  2. httpx + 瀏覽器 User-Agent → 403（Cloudflare 看的不只是 UA）
  3. Playwright headless → 顯示「請稍候...」然後擋住
  4. Playwright + stealth（反偵測） → 還是被擋

**Cloudflare 怎麼判定的**：
- 檢查 IP 信譽（雲端/VPS IP 信譽差）
- 檢查瀏覽器指紋（headless 被偵測）
- JavaScript challenge（要求執行 JS 驗證）
- TLS 指紋（httpx 的 TLS 和真實瀏覽器不同）

**要爬 Dcard，需要**：
1. **FlareSolverr Docker**（免費）— 跑一個 container 專門過 Cloudflare challenge，拿到 cookie 後傳給 httpx
2. **Residential proxy**（$5-29/月）— 用住宅 IP 而不是雲端 IP
3. **ScraperAPI / Scrapfly**（$29+/月）— 商業服務保證繞過

**結論**：API 沒問題，但 Cloudflare 擋住了。需要額外工具或付費服務。

---

## 匯總

| 平台 | 階段 | 能拿到 | 不能拿到 | 需要 |
|------|------|--------|---------|------|
| **PTT** | 第一階段 | 推文（完整） | — | 無 |
| **新聞** | 第一階段 | 報導全文 | — | 無 |
| **Threads** | 第一階段 | 貼文 + 回覆 | — | EXA_API_KEY |
| **Google Maps** | 第一階段 | 評論 + 星等 | — | SerpApi 補額度 |
| **Facebook** | 第二階段 | 貼文摘要 | 留言 | FB cookie |
| **Instagram** | 第二階段 | 搜尋摘要 | 留言 | IG 帳號 |
| **Dcard** | 第二階段 | — | 全部 | FlareSolverr / proxy |
