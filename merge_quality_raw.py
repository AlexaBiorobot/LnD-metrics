#!/usr/bin/env python3
import os
import json
import time
import logging
from typing import List, Dict, Any

import gspread
from gspread.exceptions import APIError
from google.oauth2.service_account import Credentials

# -------------------- LOGGING --------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)

# -------------------- AUTH --------------------
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# If GCP_SERVICE_ACCOUNT env var exists (JSON string), use it.
# Otherwise use local service_account.json file.
def get_client() -> gspread.Client:
    if os.getenv("GCP_SERVICE_ACCOUNT"):
        info = json.loads(os.environ["GCP_SERVICE_ACCOUNT"])
        creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    else:
        creds = Credentials.from_service_account_file("service_account.json", scopes=SCOPES)
    return gspread.authorize(creds)

# -------------------- CONFIG --------------------
# Start reading source sheets from row 2 (skip headers).
SOURCE_START_ROW = 2

MAX_RETRIES = 6
RETRY_SLEEP_SEC = 2

SOURCES: List[Dict[str, Any]] = [
    {
        "spreadsheet_id": "1yJmskKLGinBNKIV3ewXsVEfnh-JRj_FhuKyElL93vM4",
        "worksheet": "data",
        "columns": ["B", "C", "J", "K"],
        "region": "Latam",
    },
    {
        "spreadsheet_id": "1njy8V5lyG3vyENr1b50qGd3infU4VHYP4CfaD0H1AlM",
        "worksheet": "Lessons",
        "columns": ["B", "V", "J", "L"],
        "region": "Brazil",
    },
    {
        "spreadsheet_id": "1WFFz_wdZtXZQqzq0o0AObXGsTxait9LKbIbUQbSoMV8",
        "worksheet": "Storage",
        "columns": ["I", "DS", "A", "M"],
        "region": "Italy",
    },
    {
        "spreadsheet_id": "1mmlCG9YUnJ3NhEiTvyGDWGmdKNH7qrtClixLqcH_70o",
        "worksheet": "Storage",
        "columns": ["I", "DS", "A", "M"],
        "region": "Poland",
    },
    {
        "spreadsheet_id": "1nxV0u0Ag2NUs7cCqBU4zTYkGq0d9aPExqqC4RCeatsg",
        "worksheet": "Reports",
        "columns": ["C", "CA", "L", "N"],
        "region": "MENA",
    },
    {
        "spreadsheet_id": "1hQdxvhDMheOpefUudtXCMfoYlBmPFXyUL8A4HlutWv4",
        "worksheet": "Reports",
        "columns": ["C", "BZ", "L", "N"],
        "region": "Asia",
    },
    {
        "spreadsheet_id": "12jG5O-NF4uIolzPcTD8p8_yfO8TSsSRGigmqtCu3E5k",
        "worksheet": "Reports",
        "columns": ["B", "L", "J", "K"],
        "region": "ENG",
    },
]

TARGET = {
    "spreadsheet_id": "1EoEheuL204rkwsY-F7AkrjKQfWh-0PJShf9Np6k8OV0",
    "worksheet": "raw data for quality",
    "range_start": "A2",   # write from row 2
    "clear_range": "A2:E", # clear only A2:E (do not touch header row / other columns)
}

# -------------------- HELPERS --------------------
def api_retry(func, *args, **kwargs):
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return func(*args, **kwargs)
        except APIError as e:
            status = getattr(getattr(e, "response", None), "status_code", None)
            # Retry only for temporary API/server errors
            if status in (429, 500, 502, 503, 504) and attempt < MAX_RETRIES:
                sleep_for = RETRY_SLEEP_SEC * attempt
                logging.warning(f"APIError {status}, retry {attempt}/{MAX_RETRIES}, sleep {sleep_for}s")
                time.sleep(sleep_for)
                continue
            raise
        except Exception:
            if attempt < MAX_RETRIES:
                sleep_for = RETRY_SLEEP_SEC * attempt
                logging.warning(f"Unexpected error, retry {attempt}/{MAX_RETRIES}, sleep {sleep_for}s")
                time.sleep(sleep_for)
                continue
            raise

def normalize_cell(v: Any) -> str:
    return "" if v is None else str(v)

def read_source_rows(gc: gspread.Client, source: Dict[str, Any]) -> List[List[str]]:
    sh = api_retry(gc.open_by_key, source["spreadsheet_id"])
    ws = api_retry(sh.worksheet, source["worksheet"])

    col_letters = source["columns"]
    ranges = [f"{c}{SOURCE_START_ROW}:{c}" for c in col_letters]

    # One request for all needed columns
    batch = api_retry(ws.batch_get, ranges)

    # Convert each column range to plain list of values
    cols_data: List[List[str]] = []
    for col_block in batch:
        col_values = []
        for row in col_block:
            # row is usually like ["value"] or []
            if row:
                col_values.append(normalize_cell(row[0]))
            else:
                col_values.append("")
        cols_data.append(col_values)

    max_len = max((len(c) for c in cols_data), default=0)
    out_rows: List[List[str]] = []

    for i in range(max_len):
        row4 = [(c[i] if i < len(c) else "") for c in cols_data]

        # Skip fully empty rows from source
        if any(cell.strip() != "" for cell in row4):
            out_rows.append(row4 + [source["region"]])

    logging.info(
        f'{source["region"]}: pulled {len(out_rows)} rows from '
        f'{source["worksheet"]} ({source["spreadsheet_id"]})'
    )
    return out_rows

def write_target(gc: gspread.Client, rows: List[List[str]]) -> None:
    sh = api_retry(gc.open_by_key, TARGET["spreadsheet_id"])
    ws = api_retry(sh.worksheet, TARGET["worksheet"])

    # Clear only A2:E (header row and other columns remain untouched)
    api_retry(ws.batch_clear, [TARGET["clear_range"]])

    if rows:
        # Write only A:E starting from A2
        api_retry(
            ws.update,
            range_name=TARGET["range_start"],
            values=rows,
            value_input_option="RAW"
        )

    logging.info(f"Target updated: {len(rows)} rows written into A2:E")

def main():
    gc = get_client()

    all_rows: List[List[str]] = []
    for src in SOURCES:
        all_rows.extend(read_source_rows(gc, src))

    write_target(gc, all_rows)
    logging.info("Done ✅")

if __name__ == "__main__":
    main()
