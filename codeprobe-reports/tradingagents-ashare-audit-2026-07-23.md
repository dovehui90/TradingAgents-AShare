# Code Health Report — TradingAgents-AShare

**Date:** 2026-07-23
**Overall Health:** 28/100 **Critical**
**Scope:** 296 files · 67,043 LOC · Python 211 / TSX 70

---

## Dashboard

| Category | Score | Critical | Major | Minor | Suggestion | Status |
|---|---|---|---|---|---|---|
| Security | 46 | 2 | 3 | 3 | 1 | Critical |
| Error Handling | 10 | 5 | 7 | 5 | 0 | Critical |
| SOLID | 10 | 5 | 13 | 5 | 0 | Critical |
| Architecture | 10 | 4 | 6 | 6 | 1 | Critical |
| Performance | 19 | 3 | 7 | 3 | 3 | Critical |
| Code Smells | 10 | 7 | 30 | 5 | 8 | Critical |
| Testing | 62 | 0 | 5 | 4 | 4 | Needs Attention |
| Design Patterns | 78 | 0 | 3 | 2 | 1 | Needs Attention |
| Framework | 47 | 1 | 5 | 4 | 2 | Critical |
| **Total** | **28** | **27** | **79** | **37** | **20** | **Critical** |

### Codebase Stats
- Files: 296 | LOC: 67,043 | Avg method length: 35.5
- Test file ratio: 11.5% (34 files, but 7 root-level "test" files have zero assertions)
- Comment ratio: 6.8% (very low)
- Files >300 LOC: 63 | Files >500 LOC: 27
- Largest file: api/main.py (8,824 LOC, 295 definitions)

### Hot Spots
1. **api/main.py** (8,824 LOC) — flagged by all 9 categories
2. **api/services/briefing_service.py** (2,347 LOC) — flagged by 5 categories
3. **tradingagents/graph/trading_graph.py** — flagged by 3 categories
4. **tradingagents/dataflows/providers/cn_akshare_provider.py** (1,491 LOC) — flagged by 3 categories
5. **deploy.py** — hardcoded production credentials (critical security)

### Circular Dependencies
1. api/database.py → api/services/auth_service.py → api/database.py
2. tradingagents/yang_yin/__init__.py → self-import (docstring)
3. tradingagents/utils/cdp_fetch.py → self-import (docstring)

---

## Executive Summary

TradingAgents-AShare is a functionally rich A-share quantitative trading platform with substantial code quality debt. The overall health score of 28/100 reflects 27 critical findings across security, error handling, SOLID, architecture, performance, and code smells. The two most urgent issues are **hardcoded production credentials** (SEC-001: deploy.py contains root SSH password) and **hardcoded cryptographic keys** (SEC-002: JWT signing key is a default string visible in source). The primary structural problem is **api/main.py at 8,824 lines** — a God File that mixes all architectural layers and is flagged by all 9 review categories. The codebase also suffers from 102 silently swallowed exceptions (`except Exception: pass`) making production debugging nearly impossible, zero test coverage for core trading strategy logic, and 95 root-level clutter files from ad-hoc experimentation.

---

## Critical Findings (27 total)

### Security (2 critical)

**SEC-001** | critical | `deploy.py:23`
- **Problem:** Production server root credentials hardcoded in source.
- **Evidence:** `SERVER = "119.23.155.192"`, `USER = "root"`, `PASSWORD = "Qq121918="`
- **Fix:** Load from environment variables; use SSH key authentication.

**SEC-002** | critical | `api/services/auth_service.py:36-40`
- **Problem:** Hardcoded JWT signing key `"tradingagents-ashare-dev-secret"` as default.
- **Evidence:** `_DEFAULT_SECRET = "tradingagents-ashare-dev-secret"` feeds jwt.encode/decode and Fernet encryption.
- **Fix:** Remove _DEFAULT_SECRET; refuse startup without TA_APP_SECRET_KEY.

### Error Handling (5 critical)

**ERR-001** | critical | `api/main.py:4759,4769,4798,4818,4824`
- **Problem:** Five bare `except:` blocks catch SystemExit and KeyboardInterrupt.
- **Fix:** Replace with `except (ValueError, TypeError):`.

**ERR-002** | critical | `api/main.py:7773,7893`
- **Problem:** `db.commit()` without try/except, no rollback on failure.
- **Fix:** Wrap with try/except; call db.rollback() on failure.

**ERR-003** | critical | `tradingagents/dataflows/alpha_vantage_common.py:66`
- **Problem:** `requests.get()` with no timeout — thread hangs indefinitely.
- **Fix:** Add `timeout=30`.

**ERR-004** | critical | `api/main.py:4787`
- **Problem:** Hardcoded Tushare token in source as fallback.
- **Fix:** Require env var; rotate exposed token immediately.

**ERR-005** | critical | `api/main.py:6272-6291`
- **Problem:** Analysis log write wrapped in `except Exception: pass` — zero observability.
- **Fix:** Log the exception at ERROR level.

### SOLID (5 critical)

**SRP-001** | critical | `api/services/briefing_service.py:2203`
- **Problem:** `generate_briefing` orchestrates 15 parallel fetches + analysis + LLM + persistence in 350 LOC.
- **Fix:** Split into MarketDataAggregator, BriefingComposer, WatchlistAnalyzer, PortfolioAnalyzer.

**SRP-002** | critical | `api/services/briefing_service.py:1590`
- **Problem:** `_generate_trading_advice` is 411 LOC — builds data summaries, constructs prompts, calls LLM, parses response.
- **Fix:** Split into DataSummarizer, PromptBuilder, AdviceGenerator.

**SRP-003** | critical | `tradingagents/dataflows/providers/cn_akshare_provider.py`
- **Problem:** 62 methods, 1,347 LOC, spanning 8+ data domains.
- **Fix:** Split into domain-specific providers: OHLCV, Fundamental, News, FundFlow.

**DIP-001** | critical | `tradingagents/graph/trading_graph.py:58-118`
- **Problem:** `__init__` directly instantiates 10+ concrete classes — zero dependency injection.
- **Fix:** Create GraphDependencies dataclass; inject via constructor.

**DIP-002** | critical | `api/services/briefing_service.py:1942-1967`
- **Problem:** Business logic directly imports LLM factory with hardcoded provider_map.
- **Fix:** Define BriefingLLMProvider protocol; inject it.

### Architecture (4 critical)

**ARCH-001** | critical | `api/main.py` (8,824 LOC)
- **Problem:** Single file contains all layers: 105 Pydantic models, 99 routes, business logic, caching, scheduling.
- **Fix:** Split into api/schemas/, api/routers/, api/dependencies/, api/utils/.

**ARCH-002** | critical | `api/main.py:3178,4157,4787,5125`
- **Problem:** Hardcoded Tushare token in 4 locations (cross-ref: SEC-003, ERR-004).
- **Fix:** Remove all defaults; require env var; rotate token.

**ARCH-003** | critical | `api/database.py ↔ api/services/auth_service.py`
- **Problem:** Direct circular import: database imports auth_service for crypto, auth_service imports database for ORM models.
- **Fix:** Extract crypto utilities to api/services/crypto_utils.py.

**ARCH-004** | critical | `api/services/auth_service.py:36`
- **Problem:** Hardcoded JWT secret (cross-ref: SEC-002).
- **Fix:** Remove fallback; require TA_APP_SECRET_KEY.

### Performance (3 critical)

**PERF-001** | critical | `api/services/accuracy_service.py:345-351`
- **Problem:** N+1 query — loops over reports, queries backtest record per iteration.
- **Fix:** Batch fetch with `IN` query; build dict lookup.

**PERF-002** | critical | `scheduler/main.py:349-358`
- **Problem:** N+1 query — stale task recovery queries report per iteration.
- **Fix:** Batch fetch all report_ids; build set for O(1) lookup.

**PERF-003** | critical | `api/services/scheduled_service.py:315-326`
- **Problem:** `.all()` loads all active tasks into memory; filters in Python not SQL.
- **Fix:** Push trigger_time filter into SQL WHERE; add LIMIT.

### Code Smells (7 critical)

**SMELL-001** | critical | `api/main.py` (8,824 LOC, cross-ref: ARCH-001)
- **Problem:** God File — 295 definitions, all layers mixed.

**SMELL-002** | critical | `api/main.py:2220-2871` — `_run_job_inner` 652 LOC, nesting depth 8.

**SMELL-003** | critical | `tradingagents/graph/data_collector.py:87-800` — `_compute_vpa_indicators` 714 LOC, nesting depth 9.

**SMELL-004** | critical | `tradingagents/strategy/fact_engine.py:384-877` — `evaluate_rules` 39 copy-paste if-blocks.

**SMELL-005** | critical | `tradingagents/dataflows/providers/cn_akshare_provider.py` — 1,351 LOC, 54 methods (cross-ref: SRP-003).

**SMELL-006** | critical | `tradingagents/strategy/volume_price_strategy.py:194-1261` — 1,068 LOC class, 66 bool fields.

**SMELL-007** | critical | `api/services/briefing_service.py:1590-2000` — `_generate_trading_advice` 411 LOC (cross-ref: SRP-002).

---

## Major Findings Summary (79 total)

Key themes across major findings:

- **ERR-006** — 50+ `except Exception: pass` across api/main.py (all silently swallowed)
- **ERR-007** — 6 silent exception passes in Tushare data provider
- **ERR-008** — 5 silent exception passes in screener cache module
- **ERR-011** — 12 silent exception passes in briefing service scraping
- **SMELL-008 through SMELL-032** — 25 long methods/large classes across the codebase
- **SRP-004 through DIP-006** — 13 SOLID violations in trading graph, strategy, and data layers
- **ARCH-005 through ARCH-011** — Anemic domain models, transaction script anti-pattern, root clutter
- **PERF-004 through PERF-010** — Missing indexes, unbounded queries, race conditions, sequential async
- **FWK-001 through FWK-006** — Sync DB in async handler, mega React components, eslint-disable, DOM manipulation
- **TEST-001 through TEST-005** — Zero-test strategy/yang_yin packages, fake test files, untested LLM validators

---

## Prioritized Fix Order (Top 10)

1. **SEC-001** — Remove hardcoded production credentials from deploy.py
2. **SEC-002** — Remove hardcoded JWT secret key; enforce TA_APP_SECRET_KEY
3. **SEC-003** — Remove and rotate hardcoded Tushare token (6 locations)
4. **ARCH-003** — Break database.py ↔ auth_service.py circular dependency
5. **ERR-006** — Add logging to 50+ `except: pass` sites in api/main.py
6. **SMELL-001** — Begin decomposing api/main.py (extract schemas first, then routers)
7. **ERR-002** — Add rollback on db.commit() failure
8. **PERF-001** — Fix N+1 query in accuracy_service backfill
9. **DIP-001** — Add dependency injection to TradingAgentsGraph
10. **TEST-002** — Write unit tests for tradingagents/strategy/

---

## Duplicates Removed

Due to multi-category overlap, the following cross-references were noted (primary finding kept, duplicates dropped from counts):
- SEC-002 = ARCH-004 (JWT secret) → kept SEC-002
- SEC-003 = ARCH-002 = ERR-004 (Tushare token) → kept SEC-003
- ARCH-001 = SMELL-001 (api/main.py God File) → kept ARCH-001
- SRP-001 = ARCH-008 = SMELL-024 (briefing_service) → kept SRP-001
- SRP-003 = SMELL-005 (CnAkshareProvider) → kept SRP-003
- DIP-001 = SRP-004 (trading_graph constructor) → kept DIP-001
- ERR-006 partially overlaps SMELL-033 → kept both (different scope: error handling vs code smell)

---

*Report generated by codeprobe v2.2.0 on 2026-07-23*
