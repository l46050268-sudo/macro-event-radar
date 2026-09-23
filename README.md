# Macro Event Radar | 宏观与地缘事件雷达

An official-source-first desktop radar for market-relevant macro, policy, central-bank, energy, sanctions, trade-control, and geopolitical events.

面向宏观与地缘事件驱动研究的桌面信息雷达。项目聚合公开信源，保留原文链接，并提供事件分类、重要性评分、实体识别、影响资产映射和中文翻译。

> This is an experimental information-monitoring tool, not investment advice or an execution system. Polling frequency does not guarantee that a source has published new information or that an alert will arrive within a fixed latency.

## What it does

- Collects public RSS/Atom feeds and configured public pages.
- Normalizes and deduplicates items, then classifies event types and identifies entities.
- Scores market relevance and maps events to potentially affected assets.
- Stores events and translation cache in a local SQLite database.
- Provides a Windows GUI and a command-line interface, with an optional JSON webhook.
- Preserves the original headline and source link for review.

The source configuration contains 180 public links in this snapshot: 153 enabled and 27 disabled. Availability and publisher behavior change over time. Selected fast feeds are checked every 60 seconds while the app is open; other sources use their configured intervals. The source itself controls when an item is published, so this is not a guaranteed real-time newswire.

## Run on Windows

Python 3.11 or newer is required to run from source.

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python run_gui.py
```

To use the command-line interface:

```powershell
.venv\Scripts\macro-radar --limit 10 --json
.venv\Scripts\macro-radar --list --min-score 70
```

Build a one-file Windows executable with PyInstaller:

```powershell
.venv\Scripts\python -m PyInstaller --noconfirm --clean MacroEventRadar.spec
```

The executable is written to `dist\MacroEventRadar.exe`. Runtime data and logs are created beside the executable in `data` and `logs`.

## Configure sources and rules

- `config/sources.yaml` lists source URLs, trust levels, topics, enabled state, and polling interval.
- `config/rules.yaml` contains event classification, relevance, scoring, and asset-mapping rules.
- `docs/SOURCES.md` explains source selection and access boundaries.
- `docs/ARCHITECTURE.md` describes the collection and processing pipeline.

The default source list is editable. Before enabling a source, check its current terms, robots policy, rate limits, and feed availability. Commercial services such as Reuters/LSEG, Bloomberg, Newsquawk, MNI, and Dataminr require the user's own authorized subscription or API; this project does not bypass logins or paywalls.

## Optional webhook

Set `RADAR_WEBHOOK_URL` in the process environment to send qualifying new events as JSON. For example, in PowerShell:

```powershell
$env:RADAR_WEBHOOK_URL = "https://your-service.example/hooks/macro"
$env:RADAR_MIN_PUSH_SCORE = "75"
$env:RADAR_MAX_PUSH_AGE_HOURS = "24"
.venv\Scripts\macro-radar
```

Keep webhook URLs and other credentials out of source control. `.env.example` contains placeholders only.

## Translation and local data

The GUI uses public Google Translate and MyMemory translation endpoints without a membership requirement. Public headlines and source-provided summaries may be sent to those services for translation; results are cached locally. Event data, translation cache, and logs are stored on the computer running the app.

## Contributing

Bug reports and pull requests are welcome. When suggesting a source, include its official feed/page URL, publication cadence, access terms, and the market event types it helps detect. Do not submit credentials, private databases, or copied paywalled articles.

## License

MIT. See [LICENSE](LICENSE).
