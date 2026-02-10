#!/usr/bin/env python3
import os
import json
import time
import logging
from typing import List, Dict, Any
from datetime import date, timedelta, datetime

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

def get_client() -> gspread.Client:
    if os.getenv("GCP_SERVICE_ACCOUNT"):
        info = json.loads(os.environ["GCP_SERVICE_ACCOUNT"])
        creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    else:
        creds = Credentials.from_service_account_file("service_account.json", scopes=SCOPES)
    return gspread.authorize(creds)

# -------------------- CONFIG --------------------
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
    "range_start": "A2",
    "clear_range": "A2:E",
    "date_pattern": "dd.mm.yyyy",  # формат для A и C
}

# -------------------- HELPERS --------------------
def api_retry(func, *args, **kwargs):
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return func(*args, **kwargs)
        except APIError as e:
            status = getattr(getattr(e, "response", None), "status_code", None)
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

def to_text(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()

def to_sheet_date(v: Any) -> str:
    """
    Возвращает дату в формате YYYY-MM-DD, чтобы Sheets корректно распознало USER_ENTERED.
    Если распарсить не удалось — возвращает исходное значение как текст.
    """
    if v is None:
        return ""

    # Если пришло число (часто так выглядят даты при UNFORMATTED_VALUE)
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        num = float(v)
        # Типичный диапазон серийных дат Google Sheets
        if 20000 <= num <= 80000:
            d = date(1899, 12, 30) + timedelta(days=num)
            return d.strftime("%Y-%m-%d")
        return to_text(v)

    s = str(v).strip()
    if not s:
        return ""

    s = s.replace("-", "-").replace("–", "-")

    # В первую очередь day/month, т.к. у тебя данные такого вида встречаются чаще
    formats = [
        "%d.%m.%Y", "%d.%m.%y",
        "%d/%m/%Y", "%d/%m/%y",
        "%Y-%m-%d",
        "%d-%m-%Y", "%d-%m-%y",
        "%m/%d/%Y", "%m/%d/%y",  # fallback
    ]

    for fmt in formats:
        try:
            dt = datetime.strptime(s, fmt).date()
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            pass

    return s  # если это не дата, оставляем как есть

def re
