# 各平台評論爬取策略

> 本文件說明每個平台如何爬取評論，供團隊討論確認。
> 測試日期：2026-04-16，測試環境：WSL2 Ubuntu + Playwright headless Chromium

---

## 測試結果總覽

| 平台 | 方式 | 測試結果 | 能拿到留言？ |
|------|------|---------|------------|
| **PTT** | httpx + BeautifulSoup | OK | 推/噓/箭頭 全部可解析 |
| **Dcard** | httpx API / Playwright | BLOCKED (Cloudflare) | API 和 Playwright 都被擋 |
| **Google Maps** | SerpApi API | OK（額度用完但機制正常） | 個別評論+星等 |
| **Google Maps** | Playwright headless | FAIL | headless 模式評論區不渲染 |
| **新聞** | Google News RSS | OK（100篇） | 新聞標題+連結+來源 |
| **Instagram** | Playwright | 需登入 | 無法不登入爬取 |
| **Instagram** | Exa API 間接搜尋 | OK（5筆） | 貼文摘要（非留言） |
| **Threads** | Playwright（不登入） | OK | 公開頁面貼文+回覆都可爬 |
| **Threads** | Exa API 間接搜尋 | OK（5筆） | 貼文摘要 |
| **Facebook** | facebook-scraper | 未測試 | 需 cookie |

---

## 1. PTT — OK

**方式**：httpx + BeautifulSoup 解析推文

**測試結果**：
```
[dog] 搜「狗園」: 20 篇
推文數: 4
  噓 marathons:  教母在多板被水桶,到處流竄洗文貼簽名檔宣教.
  → KingChang711:  回主題，狗園好不好我先保留，得實際看過才能評論
```

**流程**：
1. httpx + cookie `over18=1` 搜尋看板（pet, dog, cat, AnimalForest, AnimalRight, Gossiping, WomenTalk）
2. `https://www.ptt.cc/bbs/{board}/search?q={entity_name}`
3. 進入每篇文章，解析 `div.push`：
   - `span.push-tag`：推 / 噓 / →
   - `span.push-userid`：留言者 ID
   - `span.push-content`：留言內容
   - `span.push-ipdatetime`：時間

**需要**：無
**風險**：低
**優先級**：最高

---

## 2. Dcard — BLOCKED

**測試結果**：Cloudflare 完全擋住
- httpx API 回 403
- Playwright headless 也被檢測擋住（頁面顯示「請稍候...」）
- 加 stealth 模式（移除 webdriver flag）仍被擋

**可行方案**：
- A) 等 Cloudflare cooldown（間歇性可用，不穩定）
- B) 用真實瀏覽器 + proxy（成本高，風險高）
- C) 用 Exa/SerpApi `site:dcard.tw` 間接搜尋（只拿到文章摘要，無留言）

**建議**：先用方案 C 間接搜尋，等 API cooldown 時自動切換直接爬取
**優先級**：中（不穩定）

---

## 3. Google Maps 評論 — OK（用 SerpApi）

**方式**：SerpApi `google_maps_reviews` API

**測試結果**：API 額度用完（402），但之前已驗證機制正常，可爬到個別評論+星等+使用者名稱

**Playwright 替代方案**：FAIL
- headless Chromium 載入 Google Maps 後，評論區不渲染（可能需要登入或 JS 動態載入問題）
- 不建議用 Playwright 爬 Google Maps

**流程（SerpApi）**：
1. `engine=google_maps q={entity} hl=zh-TW` → 取得 place_id
2. `engine=google_maps_reviews place_id={id} sort_by=newestFirst` → 取得評論
3. 每則：user_name, rating(1-5), snippet, link

**需要**：`SERPAPI_API_KEY`（需要補充額度）
**優先級**：高

---

## 4. 新聞 — OK

**方式**：Google News RSS

**測試結果**：
```
RSS status: 200, 新聞數: 100
  [自由時報] 驚！中市動物之家收容流浪犬死亡率3成
  [臺北旅遊網] 「狗狗春遊趣」景勤狗活動區超萌登場
```

**流程**：
1. `https://news.google.com/rss/search?q={entity}&hl=zh-TW&gl=TW`
2. 解析 XML feed，取得標題、來源、連結、日期
3. 可選用 trafilatura 抓全文

**需要**：無
**優先級**：中

---

## 5. Instagram — 需登入

**Playwright 測試**：需要登入，headless 無法繞過
**Exa 間接搜尋**：OK，可取得公開貼文摘要
```
[Instagram] 5 筆結果
  臺北市動物之家｜內湖最溫暖的地方 - Instagram
```

**建議方案**：用 Exa `site:instagram.com "{entity}"` 間接搜尋
**限制**：只能拿到搜尋引擎索引的貼文摘要，無法取得留言
**需要**：`EXA_API_KEY`
**優先級**：低

---

## 6. Threads — OK（Playwright 不登入可爬）

**測試結果**：Playwright 可以不登入爬取公開個人頁面和貼文回覆
```
貼文連結數: 17
進入貼文後：可以看到原文 + 所有回覆
  adopt.yourfamily: 好不容易有家的米腸走失了
  yuru88615: 請幫忙轉發分享，讓小寶貝回到溫暖的家
  tokyoace2001: 好不容易幸福的孩子，請大家幫忙分享！
```

**流程**：
1. Playwright 訪問 Threads 搜尋或公開 profile 頁面
2. 搜尋結果第一次載入可看到貼文（但之後可能要登入）
3. 公開 profile 頁面 `https://www.threads.net/@{username}` 不需登入
4. 個別貼文頁面 `https://www.threads.net/@{user}/post/{id}` 可看到回覆
5. 用 `page.inner_text('body')` 提取貼文和回覆文字

**限制**：
- 搜尋頁面不穩定（有時需登入）
- 需要先知道相關的 Threads 帳號名稱
- 或用 Exa 先搜到帳號/貼文 URL，再用 Playwright 爬回覆

**建議方案**：Exa 搜尋取得 URL → Playwright 爬取完整回覆
**需要**：`EXA_API_KEY` + Playwright
**優先級**：中

---

## 7. Facebook — 未測試

**方式**：`facebook-scraper` library（已安裝）

**流程**：
1. 提供 Facebook cookies 和目標粉絲頁 ID
2. 爬取貼文 + `options={"comments": True}` 開啟留言爬取
3. 取得 comment_text, commenter_name, comment_time

**需要**：Facebook cookies 檔案 + 粉絲頁 ID
**風險**：中高（非官方 library，Meta 會封號）
**優先級**：中

---

## 8. 官方網站 — 未測試

**方式**：httpx / trafilatura 爬取政府公開網站

**流程**：
1. 維護官方來源清單（各縣市動保處、農業部等）
2. 爬取指定頁面，搜尋是否提及 entity
3. 存成 review

**需要**：無
**風險**：低
**優先級**：中

---

## 最終建議實作順序

| 順序 | 平台 | 方式 | 難度 |
|------|------|------|------|
| 1 | PTT | httpx 推文解析 | 低（改現有 scraper） |
| 2 | Google Maps | SerpApi API | 低（已有 scraper，需補額度） |
| 3 | 新聞 | Google News RSS | 低（已有 service） |
| 4 | Threads | Exa + Playwright | 中 |
| 5 | Instagram | Exa 間接搜尋 | 低（只有摘要） |
| 6 | Facebook | facebook-scraper | 中（需 cookie） |
| 7 | 官方 | httpx / trafilatura | 低 |
| 8 | Dcard | 等 Cloudflare cooldown / Exa 間接 | 高（不穩定） |

## 需要準備的東西

- [ ] SerpApi 補充額度（Google Maps 評論用）
- [ ] Facebook cookie 檔案（如果要爬 FB）
- [ ] 確認 Exa API 額度是否足夠
- [ ] 決定 Dcard 被擋要用什麼替代方案
