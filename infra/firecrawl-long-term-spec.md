# Animal Welfare Verifier Long-Term Spec

## Goal

This spec defines the long-term product and technical plan for:

1. Firecrawl-based scheduled search and database accumulation
2. An `動保法模式` button that narrows search and answer behavior to animal-related issues only

The target outcome is to evolve the current system from a live-search MVP into a database-first platform with better signal quality, lower long-term cost, and clearer user intent modes.

## Product Direction

### Current State

The current product is primarily a live search flow:

1. User enters an entity and a question
2. Backend expands query variants
3. Backend searches the web
4. Backend filters and summarizes results
5. Results are returned and partially persisted

This is a good MVP, but it has long-term weaknesses:

- results can be noisy
- quality varies by search session
- each query re-pays search cost
- the product accumulates search history, but not enough structured entity knowledge

### Target State

The long-term target is:

`database-first search platform with scheduled refresh and optional animal-law-focused mode`

Core behavior:

1. The system tracks watched entities
2. Firecrawl regularly refreshes relevant public sources for those entities
3. Cleaned results are stored in the platform database
4. User searches read from stored evidence first
5. Live search is only used as a supplement when the database is stale or insufficient
6. `動保法模式` narrows search, filtering, and summaries to animal-related issues only

## Scope

This spec covers:

- long-term Firecrawl usage strategy
- database and data-flow design
- scheduled crawling design
- search mode behavior
- `動保法模式` toggle behavior
- API and frontend requirements

This spec does not cover:

- ad insertion strategy
- billing or rate limiting implementation
- public moderation workflows for user-submitted evidence

## Guiding Principles

1. Database first, live search second
2. Firecrawl is the acquisition layer, not the whole platform
3. Animal-law mode must be stricter than normal search
4. If content is not clearly related to animal welfare, it should be excluded in animal-law mode
5. The system should prefer refusing low-confidence legal answers over overclaiming

## Firecrawl Long-Term Architecture

### Firecrawl's Role

Firecrawl should be used for:

- search result discovery
- page content extraction
- optional targeted crawl of high-value sources

Firecrawl should not be treated as:

- the long-term database
- the source ranking system by itself
- the moderation layer
- the legal reasoning layer

### Recommended Operating Model

Use Firecrawl in two modes:

1. Scheduled refresh mode
   - run on watchlisted entities at fixed intervals
   - save cleaned results into database

2. Live supplement mode
   - triggered by user query only when stored data is insufficient
   - merge new sources into database after filtering

### Long-Term Data Flow

1. Admin or system creates a watched entity
2. System builds search keyword sets for that entity
3. Scheduler triggers Firecrawl search jobs
4. Search results are normalized and deduplicated
5. Relevant pages are extracted or crawled for content
6. AI filtering removes low-signal and unrelated content
7. Remaining sources are scored and linked to the entity
8. Entity summaries and evidence caches are refreshed
9. User-facing search reads from the stored entity profile first

## Entity-Centered Database Model

### Why Entity-Centered

The platform should no longer think in terms of only:

`question -> one-off results`

It should think in terms of:

`entity -> tracked keywords -> scheduled sources -> structured evidence`

### Existing Reusable Tables

The current system already has a useful base:

- `entities`
- `search_queries`
- `sources`
- `query_summaries`
- `evidence_cards`
- `media_files`

These should be preserved and extended.

### New Tables

#### `entity_watchlists`

Purpose:
- decides which entities get refreshed automatically

Suggested columns:

- `id`
- `entity_id`
- `is_active`
- `refresh_interval_hours`
- `priority`
- `last_crawled_at`
- `next_crawl_at`
- `last_success_at`
- `last_error_at`
- `last_error_message`
- `created_at`
- `updated_at`

#### `entity_keywords`

Purpose:
- stores the actual tracked keyword set per entity

Suggested columns:

- `id`
- `entity_id`
- `keyword`
- `keyword_type`
- `weight`
- `is_active`
- `created_at`
- `updated_at`

Suggested `keyword_type` values:

- `primary_name`
- `alias`
- `anonymous_variant`
- `animal_issue`
- `fundraising`
- `manual`

#### `crawl_jobs`

Purpose:
- tracks scheduled refresh runs

Suggested columns:

- `id`
- `entity_id`
- `job_type`
- `status`
- `started_at`
- `finished_at`
- `source_count`
- `accepted_count`
- `rejected_count`
- `error_message`
- `created_at`

Suggested `job_type` values:

- `scheduled_refresh`
- `manual_refresh`
- `live_supplement`

#### `source_entity_matches`

Purpose:
- links stored sources to entities with per-entity scoring

Suggested columns:

- `id`
- `entity_id`
- `source_id`
- `matched_keyword`
- `relevance_score`
- `animal_related_score`
- `is_noise`
- `needs_review`
- `created_at`
- `updated_at`

#### `entity_summary_snapshots`

Purpose:
- stores precomputed entity summaries so frontend can load fast

Suggested columns:

- `id`
- `entity_id`
- `mode`
- `summary_json`
- `source_window_days`
- `created_at`

Suggested `mode` values:

- `general`
- `animal_law`

## Search Modes

### General Mode

Default mode.

Behavior:

- broader entity reputation search
- includes reviews, controversies, fundraising, statements, public discussion
- may include animal-related and non-animal-related sources

Use cases:

- 最近評價如何
- 有沒有爭議
- 募資是否透明

### Animal-Law Mode

Triggered by frontend toggle button.

Behavior:

- stricter query expansion
- stricter filtering
- stricter summary scope
- only returns content clearly related to animals, animal welfare, animal treatment, sheltering, breeding, environment, injuries, deaths, neglect, abuse, abandonment, rescue, or relevant regulation

Use cases:

- 是否有動物福利疑慮
- 是否涉及動保法相關問題
- 哪些內容與動物照護或違規風險有關

Non-goals:

- general reputation search
- unrelated celebrity, gossip, business, or event complaints
- broad legal advice outside animal-related topics

## `動保法模式` Button Spec

### UX Goal

The button is a mode toggle, not a separate page.

When enabled:

- the query is interpreted through an animal-related lens
- unrelated content should be dropped earlier
- summaries should focus on animal welfare and possible legal relevance

### Suggested UI Label

Recommended label:

- `動保法模式`

Alternative labels:

- `只看動物相關`
- `動物專注模式`

### Frontend Behavior

When toggle is off:

- normal query suggestions remain
- standard search flow is used

When toggle is on:

- send `animal_focus: true` in search requests
- update placeholder and quick tags
- visually indicate stricter mode is active
- optionally show a short note:
  - `只顯示與動物福利、照護、疑似違規或動保法相關的內容`

### Backend Behavior

When `animal_focus = true`:

1. query expansion should add animal-related keywords
2. non-animal-related results should be removed early
3. ranking should prioritize animal welfare relevance
4. summaries should only discuss animal-related concerns
5. legal-style wording must remain cautious

## Query Strategy

### General Query Expansion

Use the current query logic as baseline, including:

- entity name
- aliases
- platform-targeted queries
- controversy and fundraising queries

### Animal-Law Query Expansion

When `animal_focus = true`, add stricter templates such as:

- `{base} 動保`
- `{base} 動保法`
- `{base} 動物福利`
- `{base} 虐待`
- `{base} 棄養`
- `{base} 飼養環境`
- `{base} 超收`
- `{base} 死亡`
- `{base} 照護`
- `{base} 非法繁殖`
- `{base} 收容`
- `{base} 救援`
- `{base} 絕育`
- `{base} 展演`
- `{base} 稽查`
- `{base} 裁罰`
- `site:news {base} 動保`
- `site:ptt.cc/bbs {base} 虐待`
- `site:dcard.tw {base} 動物`

### Anonymous and Fuzzy Keyword Support

The platform should support secondary keyword variants, but only where configured.

Examples:

- shortened names
- masked names
- known aliases
- community nicknames

These should be stored in `entity_keywords` and not guessed blindly for every entity.

## Filtering Rules

### Shared Filtering

All modes should filter:

- empty template pages
- login and placeholder pages
- duplicate URLs
- low-signal scraped content
- social profile pages with no evidence content

### Animal-Law Mode Filtering

Animal-law mode should additionally reject content that:

- mentions the entity but not animals
- is only about shopping, exhibitions, queue complaints, entertainment, or unrelated life updates
- is a generic repost with no animal-related signals
- contains no meaningful overlap with animal welfare markers

Suggested animal-related markers:

- 動物
- 狗
- 貓
- 毛孩
- 收容
- 救援
- 棄養
- 虐待
- 受傷
- 死亡
- 飼養
- 籠養
- 超收
- 惡臭
- 環境
- 照護
- 醫療
- 絕育
- 繁殖
- 非法繁殖
- 展演
- 稽查
- 裁罰
- 動保法

### Scoring in Animal-Law Mode

Recommended score dimensions:

- entity relevance
- animal-related relevance
- evidence strength
- first-hand proximity
- source credibility
- recency

Animal-law mode should strongly demote:

- unrelated news aggregation
- general reputation content
- event complaints with no animal connection

## Scheduled Refresh Design

### Scheduling Strategy

Recommended first version:

- use `APScheduler` in backend or a separate scheduled worker
- refresh high-priority entities every 6 hours
- refresh normal entities every 24 hours

Later options:

- dedicated worker process
- system cron
- cloud scheduler

### Refresh Job Steps

For each watchlisted entity:

1. load active keywords
2. generate search phrases
3. call Firecrawl search
4. deduplicate URLs
5. extract or crawl selected pages
6. run low-signal filters
7. run animal-related classifier if needed
8. write accepted sources to database
9. update source-entity matches
10. update entity summary snapshot
11. record crawl job result

### Refresh Frequency

Recommended first-pass defaults:

- priority 1 entities: every 6 hours
- priority 2 entities: every 12 hours
- priority 3 entities: every 24 hours

## Search API Changes

### Existing Endpoint

Current main entry:

- `POST /api/search`

### Request Changes

Add:

```json
{
  "entity_name": "string",
  "question": "string",
  "animal_focus": true
}
```

Default:

- `animal_focus = false`

### Response Changes

Recommended additions:

- `search_mode`
- `used_cached_summary`
- `used_live_supplement`
- `animal_focus`

Example:

```json
{
  "mode": "live",
  "search_mode": "animal_law",
  "animal_focus": true,
  "used_cached_summary": true,
  "used_live_supplement": false
}
```

## Search Execution Policy

### Database-First Policy

For all requests:

1. try loading recent entity summary snapshot
2. if enough evidence exists, return cached result
3. if evidence is stale or too sparse, run Firecrawl supplement search
4. merge new sources and refresh summary

### Suggested Staleness Rules

General mode:

- reuse cache if refreshed within 7 days and source count is adequate

Animal-law mode:

- reuse cache if refreshed within 3 days and source count is adequate

Fallback live search should happen when:

- entity is new
- cache is stale
- source count is too low
- animal mode cache has too few animal-related sources

## Summary Generation Rules

### General Mode Summary

May discuss:

- positive vs negative reputation
- controversy
- fundraising concerns
- official statements
- third-party reporting

### Animal-Law Mode Summary

Must only discuss:

- animal welfare concerns
- treatment and care concerns
- sheltering or breeding issues
- possible regulation relevance
- evidence gaps

Must not discuss:

- unrelated personal reputation
- unrelated business or entertainment issues
- broad legal conclusions without support

### Legal Wording Rules

Animal-law mode summaries and bot answers must use cautious language such as:

- `可能涉及`
- `依目前公開資料可能與下列問題有關`
- `仍需主管機關或完整證據進一步認定`
- `目前可支持的部分`
- `目前無法確認的部分`

Must avoid:

- `一定違法`
- `已證實犯罪`
- `可直接定罪`

## Animal-Law Bot Spec

### Product Intent

This is not a general chatbot.

It is a constrained, animal-related legal-information helper that is enabled by a button-driven mode.

### Entry Behavior

When `動保法模式` is enabled:

- search becomes animal-focused
- legal assistant behavior becomes available
- answer scope becomes narrower

### Answer Policy

The bot should only answer if the user request is clearly related to:

- animals
- shelters
- rescue
- breeding
- care conditions
- abuse
- abandonment
- injury
- death
- overcrowding
- environmental conditions
- welfare concerns
- animal-law related regulations

If the request is not animal-related, it should refuse and say the mode only handles animal-related issues.

### Retrieval Policy

The bot should use a strict source whitelist for legal answers.

Recommended initial sources:

- Animal Protection Act text
- implementing rules
- relevant official guidance
- penalty guidance or administrative explanations, if available

The bot should not answer legal questions from general web noise.

### Prompt Policy

The bot must:

- answer only from retrieved animal-related legal materials
- refuse unsupported claims
- state uncertainty when evidence is incomplete
- suggest what additional facts are needed

The bot must not:

- make non-animal legal judgments
- act as a general lawyer bot
- label someone definitively illegal from sparse evidence

## Implementation Phases

### Phase 1: Mode Toggle and Backend Wiring

Deliverables:

- add `animal_focus` to search request model
- add frontend toggle button
- add stricter query templates and filters
- adjust summary prompt for animal mode

Success criteria:

- toggle visibly changes result quality
- unrelated content is significantly reduced in animal mode

### Phase 2: Watchlist and Scheduled Refresh

Deliverables:

- add watchlist and keyword tables
- add scheduled refresh job runner
- persist crawl job logs
- refresh entity snapshots

Success criteria:

- important entities refresh automatically
- repeated user searches hit stored data first

### Phase 3: Database-First Search

Deliverables:

- cache freshness checks
- entity summary snapshot loading
- live supplement fallback

Success criteria:

- faster result load
- lower repeated search cost
- more stable summaries

### Phase 4: Animal-Law Bot

Deliverables:

- separate legal-answer endpoint
- strict legal retrieval whitelist
- refusal behavior for unrelated questions

Success criteria:

- bot answers stay in scope
- irrelevant questions are rejected
- legal phrasing remains cautious

## Non-Functional Requirements

### Performance

- entity profile and cached summary load should be fast enough for mobile use
- scheduled jobs should run independently of user requests

### Safety

- avoid broad legal claims
- avoid mixing unrelated gossip into animal mode
- store crawl errors for review

### Maintainability

- keep Firecrawl integration isolated in service layer
- separate search mode logic from presentation logic
- make animal mode rules configurable, not hardcoded across multiple files

## Suggested Backend Changes

### Models

Update search request model to include:

- `animal_focus: bool = false`

### Services

Extend search service to:

- build mode-specific queries
- run mode-specific filtering
- rank with animal relevance
- support database-first result retrieval

Add new services:

- `WatchlistService`
- `ScheduledRefreshService`
- `EntitySummaryService`
- later `AnimalLawService`

### Routes

Keep:

- `POST /api/search`

Add later:

- `POST /api/entities/{entity_id}/refresh`
- `GET /api/entities/{entity_id}/snapshot`
- `POST /api/law-chat`

## Suggested Frontend Changes

### Search Form

Add:

- toggle switch for `動保法模式`

When enabled:

- placeholder changes to animal-related prompt
- quick tags change to animal-related prompts
- result header shows mode is active

### Results

Animal mode result cards should emphasize:

- why this source is animal-related
- possible welfare concern type
- evidence strength
- whether legal relevance is direct or indirect

## Example User Flows

### Flow A: General Search

1. User searches `趙媽媽狗園 最近評價如何`
2. System checks general cached summary
3. If fresh, return cached summary
4. If stale, supplement with Firecrawl and update database

### Flow B: Animal-Law Search

1. User enables `動保法模式`
2. User searches `趙媽媽狗園 是否有動物福利疑慮`
3. System only keeps animal-related sources
4. Summary focuses on welfare concerns and evidence gaps

### Flow C: Animal-Law Bot

1. User enables `動保法模式`
2. User asks `長期惡臭與超收可能涉及什麼問題`
3. Bot checks animal-law retrieval sources
4. Bot answers within scope and notes uncertainty

## Open Questions

1. Which entities should be seeded into watchlist first
2. Which aliases should be manually curated vs generated
3. Which official animal-law materials should be included in the first legal whitelist
4. Whether scheduled jobs run inside backend process or separate worker
5. Whether animal mode results should be cached separately from general mode

## Recommended First Milestone

The first implementation milestone should include:

1. frontend `動保法模式` toggle
2. backend `animal_focus` request support
3. stricter animal query expansion
4. stricter animal-related filtering
5. watchlist schema
6. scheduled Firecrawl refresh job

This creates immediate product improvement while also moving the architecture toward long-term database accumulation.
