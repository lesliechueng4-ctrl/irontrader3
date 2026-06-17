# Test layout

Tests are split by runtime dependency.

## Unit tests

`tests/unit/` contains deterministic tests that should run without live market
data, a running Flask server, or direct internet access. Run them from the
project root:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests/unit -t .
```

## Manual tests

`tests/manual/` contains diagnostics and live-data checks. These may call
AkShare, Sina, EastMoney, Tencent, or the local Flask app on port `5002`.

Run individual manual checks from the project root, for example:

```powershell
.\.venv\Scripts\python.exe tests\manual\test_api.py
.\.venv\Scripts\python.exe tests\manual\test_datafetcher.py
```

Do not include `tests/manual/` in the default automated test command unless the
network and local services are intentionally available.
