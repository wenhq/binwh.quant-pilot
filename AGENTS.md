# Agent Guide — binwh.quant-pilot

## Architecture

```
backend/          # FastAPI + SQLAlchemy async + MySQL
  app/
    main.py       # FastAPI entry + lifespan (scheduler)
    config.py     # Pydantic Settings (reads .env)
    database.py   # async engine + session
    models/       # 10 SQLAlchemy ORM tables
    routers/      # health, auth, data, indicators, market_regime
    services/
      auth/       # JWT httpOnly Cookie + BCrypt
      data/       # Multi-source engine (akshare/baostock/guosen)
      indicators/ # MACD/RSI/Bollinger/Keltner/ATR + forward/backward adj
      market_regime/ # PCA → HMM → LogisticRegression pipeline
      scheduler.py  # Daily sync at 15:05 CST
frontend/         # Vue 3 + TypeScript + Ant Design Vue 4
notebooks/        # Jupyter learning notebooks (Python → quant libs → options → viz)
docs/             # Design docs (brainstorms + plans)
```

## API Endpoints

### Health
- `GET /api/health` → `{"status":"ok"}`

### Auth (Cookie-based JWT)
- `POST /api/auth/register`
- `POST /api/auth/login` — sets httpOnly Cookie
- `POST /api/auth/refresh`
- `POST /api/auth/logout`
- `GET /api/auth/me` — requires auth

### Data
- `POST /api/data/sync/{stock_code}` — sync daily kline (akshare → MySQL)
- `GET /api/data/stock/{code}/daily` — stock daily kline
- `GET /api/data/index/{code}/daily` — index daily kline
- `GET /api/data/etf/{code}/daily` — ETF daily kline
- `GET /api/data/etfs` — ETF list + latest price/chg%
- `POST /api/data/import/batch` — batch import CSI300 + indices/ETFs
- `POST /api/data/import/retry` — retry failed imports
- `GET /api/data/import/progress` — import progress

### Indicators (asset_type: stock/index/etf)
- `GET /api/indicators/{asset_type}/{code}/macd`
- `GET /api/indicators/{asset_type}/{code}/rsi`
- `GET /api/indicators/{asset_type}/{code}/boll`
- `GET /api/indicators/{asset_type}/{code}/all` — Kline + all indicators

Reads from `indicator_values` table first; falls back to real-time compute.

### Market Regime ML
- `POST /api/market_regime/train/{market}` — train single market (A / HK)
- `POST /api/market_regime/train_all` — train all markets
- `GET /api/market_regime/states/{market}` — latest regime sequence
- `GET /api/market_regime/runs/{market}` — training history

## ML Pipeline

Features (multi-period returns, realized vol, macro diff, spread) → PCA (95% variance) → HMM (3 states, multi-seed) → LogisticRegression (state t+1 prediction) → Evaluation (KS, regime stats, episode coverage)

## Database

10 tables: users, stocks, stock_daily_klines, indices, index_daily_klines, etfs, etf_daily_klines, funds, fund_daily_klines, instruments, indicator_values, regime_runs, regime_states, import_errors

## Data Sources

- **akshare**: primary, multi-fallback (Tencent → Sina)
- **baostock**: stable A-share, no V8 dependency, thread-safe
- **guosen**: backup for indices/ETFs, circuit breaker

## Config

All config via `.env` (excluded from git). See `.env.example` for template.

## Scripts

- `scripts/run_import.py` — batch import
- `scripts/run_regime.py` — trigger regime training
- `scripts/backfill_indicators.py` — backfill indicator_values
- `scripts/fix_etf_history.py` — re-import ETF history

## Tests

16 pytest files covering auth, data sources, importer, registry, universe, indicators, market regime (features/reduce/clustering/classifier/evaluation/persist/pipeline), models. Async mode via `pytest-asyncio`.

## Agent Preferences

- Commit messages should be written in **Chinese**
