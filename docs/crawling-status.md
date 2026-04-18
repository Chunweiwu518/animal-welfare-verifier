# 爬取系統現況 — 2026-04-18 實測更新

## 帳號狀態

| 服務 | 帳號 | 額度 |
|------|------|------|
| Apify | `periwinkle_officer` (tssda.contact@gmail.com) | 免費 Plan，$5/月 credit |
| Exa | 已有 key | 正常 |
| SerpApi | 已有 key | 額度用完（需補） |

---

## 可以爬的平台（全部實測成功）

| 平台 | 方式 | 能拿到 | 費用 |
|------|------|--------|------|
| **PTT** | httpx 解析 div.push | 推/噓/箭頭 + 作者 + 內容 | 免費 |
| **新聞** | Google News RSS | 新聞標題 + 摘要 + 來源 | 免費 |
| **Threads** | Exa + Playwright | 貼文 + 回覆 | Exa key |
| **Google Maps** | SerpApi | 評論 + 星等 + 用戶名 | SerpApi（需補額度）|
| **Instagram 貼文** | Apify `apify/instagram-scraper` | hashtag/profile 貼文全文 | Apify $0 |
| **Instagram 留言** | Apify `apify/instagram-comment-scraper` | 留言者 + 完整留言內容（實測 10 則）| Apify $0 |
| **Facebook 貼文** | Apify `apify/facebook-posts-scraper` | 粉絲頁貼文全文、讚數、留言數 | Apify $0 |
| **Facebook 留言** | Apify `apify/facebook-comments-scraper` | 留言者 + 留言內容 | Apify $0 |

---

## 不能爬的平台

### Dcard

**測試過的所有方式都失敗（全部 403）**：
- httpx 直接呼叫 API
- Playwright headless + stealth
- Dcard `_api` 內部端點
- Apify proxy
- Apify web-scraper（Puppeteer + Apify proxy）
- Exa `site:dcard.tw` 搜尋（只搜到搜尋頁，非實際貼文）

**原因**：Dcard 使用 Cloudflare 最高等級的 Bot Fight Mode，連 Apify 的 residential proxy + headless browser 都被擋。

**能用的方案**：
| 方案 | 費用 |
|------|------|
| ScraperAPI 或 Scrapfly（專門繞 Cloudflare 的商業服務）| $29-49/月 |
| 用你的瀏覽器 cookie（匯出後給 scraper 用，會過期） | 免費 |
| 放棄 Dcard，用 PTT 替代 | $0 |

---

## Apify 實測成果

### Instagram 留言（實測成功！）
爬 `https://www.instagram.com/p/DPvwLWGk4fy/` 拿到 10 則留言：
```
tracy__cutie: 如果錯過報名機會五股動物之家除了每週一跟國定假日外10-12:00 14:00-16:00...
emma_hahha: 請問要如何報名志工？
huanyunliu: 請問要如何報名志工服務呢？
karen.lu.1024: 我的貓當初也是在內湖這邊領養的成貓，養了4年了...
emilyren1234: 內湖動物之家，一定要事先報名志工，才能幫忙蹓狗嗎？謝謝
```

### Facebook 貼文（實測成功！）
爬 `AnimalsTaiwan` 粉絲頁拿到 3 則貼文完整內容：
```
牠們不是過客，是在等一個家的人
在這裡，貓與狗沒有品種的光環，只有一顆顆真誠等待的心...

愛笑的點點，連拆頭套都一臉無辜
如果願意，每月500助養他，陪這個愛笑的孩子慢慢變好
```

### Facebook 留言
能爬，但粉絲頁留言本身就少（測試的 reel 只有 1 則）。

### 費用預估（免費 tier $5/月）
每次測試耗費 **$0.0000 credit**（都還在 compute units 內），$5 應該夠用好一段時間。

---

## 接下來要做

1. 建 Apify Pipeline（新增 4 個 pipeline 接 Apify）：
   - `apify_instagram_posts` — apify/instagram-scraper
   - `apify_instagram_comments` — apify/instagram-comment-scraper
   - `apify_facebook_posts` — apify/facebook-posts-scraper
   - `apify_facebook_comments` — apify/facebook-comments-scraper

2. Dcard 決策：
   - **A**：花 $29/月買 Scrapfly，接 Dcard 留言
   - **B**：放棄 Dcard（PTT 已經是台灣最大匿名論壇，功能重疊）
   - **C**：暫時放著，之後有預算再接

3. SerpApi 補額度（$50/月）→ Google Maps 評論繼續用
