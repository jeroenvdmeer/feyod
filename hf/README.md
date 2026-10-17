---
license: cc0-1.0
pretty_name: Feyod Football Match Data
task_categories:
- tabular-classification
- time-series-forecasting
tags:
- football
- soccer
- sports
- feyenoord
size_categories:
- 100K<n<1M
configs:
- config_name: matches
  data_files: "matches.parquet"
  default: true
- config_name: players
  data_files: "players.parquet"
- config_name: goals
  data_files: "goals.parquet"
- config_name: lineups
  data_files: "lineups.parquet"
- config_name: substitutions
  data_files: "substitutions.parquet"
- config_name: cards
  data_files: "cards.parquet"
- config_name: clubs
  data_files: "clubs.parquet"
- config_name: competitions
  data_files: "competitions.parquet"
- config_name: seasons
  data_files: "seasons.parquet"
---

# Feyod Football Match Data

Feyod is an open dataset of Feyenoord matches: results, scorers, cards, substitutions and lineups, from the earliest matches to the present. It is published as Parquet (one file per table) and as a ready-to-use SQLite database (`feyod.db`).

- Source repository and canonical SQL dump (`feyod.sql`): https://github.com/jeroenvdmeer/feyod
- Website: https://feyod.nl
- License: CC0 1.0 (public domain dedication).

This dataset is not affiliated with Feyenoord Rotterdam N.V.

## Provenance

Recent matches are harvested automatically. Historical matches come from historical sources (books, archives, and contemporary newspapers and 'De Feijenoorder' magazines) and are added after verification. The Parquet files and `feyod.db` are generated from the published `feyod.sql` and are faithful to it: column names, flags (0/1 integers) and date strings are unchanged.

Built from source commit `{{SOURCE_SHA}}` on `{{BUILD_DATE}}`.

## Dataset structure

| File | Description |
|---|---|
| `matches.parquet` | Main match information (dates, clubs, scores). |
| `players.parquet` | Player details. |
| `goals.parquet` | Goal events linked to matches and players. |
| `lineups.parquet` | Starting lineups and squads. |
| `substitutions.parquet` | Substitution events. |
| `cards.parquet` | Yellow and red cards. |
| `clubs.parquet` | Club information. |
| `competitions.parquet` | Competition names. |
| `seasons.parquet` | Season definitions. |
| `feyod.db` | All tables above as one SQLite database. |

Row counts in this version:

{{ROW_COUNTS_TABLE}}

## Usage

With the `datasets` library (one config per table; `matches` is the default):

```python
from datasets import load_dataset

matches = load_dataset("jeroenvdmeer/feyod", "matches")
print(matches["train"].to_pandas().head())
```

With pandas, reading a Parquet file straight from the Hub:

```python
import pandas as pd

df = pd.read_parquet("hf://datasets/jeroenvdmeer/feyod/matches.parquet")
```

With SQLite, after downloading `feyod.db`:

```python
import sqlite3

con = sqlite3.connect("feyod.db")
print(con.execute("SELECT COUNT(*) FROM matches").fetchone())
```
