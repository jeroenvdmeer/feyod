import sqlite3
import pandas as pd
import os
from huggingface_hub import HfApi, create_repo

# Configuration
SQL_FILE = 'feyod.sql'
DATA_DIR = './data'
HF_USERNAME = "jeroenvdmeer" # Assumed from path, user can change
TABLES = [
    "cards",
    "clubs",
    "competitions",
    "goals",
    "lineups",
    "matches",
    "players",
    "seasons",
    "substitutions"
]

def setup_database():
    print("Creating in-memory SQLite database...")
    conn = sqlite3.connect(':memory:')
    
    print(f"Reading SQL file: {SQL_FILE}")
    with open(SQL_FILE, 'r', encoding='utf-8') as f:
        sql_script = f.read()
    
    print("Executing SQL script...")
    conn.executescript(sql_script)
    return conn

def export_to_parquet(conn):
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)

    row_counts = {}
    for table in TABLES:
        print(f"Exporting table: {table}")
        try:
            df = pd.read_sql(f"SELECT * FROM {table}", conn)
            output_path = os.path.join(DATA_DIR, f"{table}.parquet")
            df.to_parquet(output_path, index=False)
            print(f"  -> Saved to {output_path} ({len(df)} rows)")
        except Exception as e:
            # A partial export must not silently continue to upload_to_hub() -
            # that would ship an incomplete public dataset. Fail loudly instead.
            raise RuntimeError(f"Failed to export table '{table}': {e}") from e
        row_counts[table] = len(df)

    empty_tables = [table for table, count in row_counts.items() if count == 0]
    if empty_tables:
        raise RuntimeError(
            "The following tables produced empty Parquet files, which is "
            f"unexpected for production data: {', '.join(empty_tables)}. "
            "Aborting before upload_to_hub() to avoid publishing an incomplete dataset."
        )

def create_dataset_card(repo_id):
    readme_content = f"""---
license: mit
task_categories:
- tabular-classification
- time-series-forecasting
tags:
- football
- soccer
- sports
pretty_name: Feyod Football Match Data
size_categories:
- 10K<n<100K
---

# Feyod Football Match Data (Parquet)

This dataset contains football match data converted from the `feyod.sql` database.

## Dataset Structure

The data is split into the following Parquet files, corresponding to relational tables:

| Table | Description |
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

## Usage

```python
from datasets import load_dataset

# Load a specific table (e.g., matches)
dataset = load_dataset("{repo_id}", data_files="matches.parquet")
print(dataset['train'].to_pandas().head())
```
"""
    with open(os.path.join(DATA_DIR, "README.md"), "w", encoding='utf-8') as f:
        f.write(readme_content)
    print("Created README.md (Dataset Card)")

def upload_to_hub():
    print("Authenticating with Hugging Face...")
    api = HfApi()
    
    token = os.environ.get("HF_TOKEN")
    # If token is None, HfApi uses the locally saved token from `huggingface-cli login`
    
    try:
        user_info = api.whoami(token=token)
        username = user_info['name']
        print(f"Logged in as: {username}")
    except Exception as e:
        print(f"Authentication check failed: {e}")
        print("Please ensure you are logged in using `huggingface-cli login` or set HF_TOKEN.")
        return

    repo_id = f"{username}/feyod"
    print(f"Target Repository: {repo_id}")

    try:
        print(f"Creating repository {repo_id} (if not exists)...")
        create_repo(repo_id=repo_id, repo_type="dataset", exist_ok=True, token=token)
    except Exception as e:
        print(f"Note: Repository creation might have failed (or it exists and we assume access): {e}")

    try:
        print("Uploading files...")
        api.upload_folder(
            folder_path=DATA_DIR,
            repo_id=repo_id,
            repo_type="dataset",
            token=token
        )
        print("Upload complete!")
        print(f"View your dataset at: https://huggingface.co/datasets/{repo_id}")
    except Exception as e:
        print(f"Error during upload: {e}")

def main():
    conn = setup_database()
    export_to_parquet(conn)
    conn.close()

    # Computed the same way upload_to_hub() derives its own repo_id (from the
    # authenticated whoami() username), so the README and the actual upload
    # target no longer disagree. Using HF_USERNAME here avoids duplicating
    # the whoami() API call before the upload step.
    repo_id = f"{HF_USERNAME}/feyod"
    create_dataset_card(repo_id)

    # Optional: confirm before upload or just try it
    # For this task, we'll try it if possible
    upload_to_hub()

if __name__ == "__main__":
    main()
