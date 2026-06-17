# IronTrader3 project structure

This document is the current file map after the first cleanup pass. The goal is
to keep runnable application code easy to find while keeping one-off scripts and
runtime data out of the project root.

## Keep in project root for now

Runtime entry points and modules still use flat imports, so the core source files
remain in the root until the project is converted into a package.

- `app.py` - Flask app entry point and remaining API routes.
- `scanner_routes.py` - scanner blueprint for wash-pattern and limit-down rebound endpoints.
- `run_background.py` - background Flask runner for port `5002`.
- `run_app_watchdog.ps1` - watchdog that keeps `run_background.py` running.
- `requirements.txt` - Python dependencies.
- `templates/` - Flask templates.
- `static/` - frontend JavaScript and CSS.

## Core data modules

- `data_fetcher.py`
- `data_source_client.py`
- `cache_manager.py`
- `data_cache.py`
- `data_loader.py`

## Strategy and scoring modules

- `decision_maker.py`
- `decision_maker_enhanced.py`
- `risk_engine.py`
- `stock_selector.py`
- `chip_quality_strategy.py`
- `config.py` (含 `ChipQualityParams`，原 `config_chip_quality.py` 已合并至此)
- `strategy_enhancements.py`
- `low_buy_engine.py`
- `market_sentiment.py`
- `sector_flow_scorer.py`
- `sector_money_flow.py`
- `stock_fund_analyzer.py`
- `technical_scorer.py`
- `fundamental_scorer.py`

## ML and RAG modules

- `future_predictor.py`
- `features.py`
- `model_engine.py`
- `rag_engine.py`

## Scanner modules

- `scanner_routes.py`
- `wash_pattern_scanner.py`
- `stock_screener_2.py`

`scanner_routes.py` now resolves scanner scripts from environment variables or
from files placed in the current project root. It no longer falls back to a
machine-specific legacy path.

## Scripts

- `scripts/research/` - one-off research, data inspection, and market debugging scripts.
- `scripts/manual/` - manual smoke checks and local UI/debug helpers.
- `scripts/examples/` - example usage scripts referenced by documentation.
- `scripts/tools/` - project maintenance tools such as GitHub repository creation.

The GitHub creation scripts read `GITHUB_TOKEN` from the environment and no
longer store a token in source code.

## Tests

- `tests/unit/` - deterministic tests that should run without live market data,
  a running Flask server, or direct internet access.
- `tests/manual/` - diagnostics and live-data checks that may call AkShare,
  Sina, EastMoney, Tencent, or the local Flask app on port `5002`.

Default unit test command:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests/unit -t .
```

## Runtime artifacts

These should remain untracked and are covered by `.gitignore`:

- `.venv/`
- `cache/`
- `outputs/`
- `__pycache__/`
- `*.log`
- `*.pid`
- generated scanner CSV output, including `outputs/scanners/`
