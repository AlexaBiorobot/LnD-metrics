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

def read_source_rows(gc: gspread.Client, source: Dict[str, Any]) -> List[List[str]]:
    sh = api_retry(gc.open_by_key, source["spreadsheet_id"])
    ws = api_retry(sh.worksheet, source["worksheet"])

    col_letters = source["columns"]
    ranges = [f"{c}{SOURCE_START_ROW}:{c}" for c in col_letters]

    # UNFORMATTED_VALUE помогает получать настоящие числа/даты из ячеек
    batch = api_retry(
        ws.batch_get,
        ranges,
        value_render_option="UNFORMATTED_VALUE"
    )

    cols_data: List[List[Any]] = []
    for col_block in batch:
        col_values = []
        for row in col_block:
            if row:
                col_values.append(row[0])
            else:
                col_values.append("")
        cols_data.append(col_values)

    max_len = max((len(c) for c in cols_data), default=0)
    out_rows: List[List[str]] = []

    for i in range(max_len):
        row4 = [(c[i] if i < len(c) else "") for c in cols_data]

        if any(to_text(x) != "" for x in row4):
            # A (index 0) и C (index 2) приводим к дате
            row4[0] = to_sheet_date(row4[0])
            row4[2] = to_sheet_date(row4[2])

            # Остальное приводим к тексту
            row4 = [to_text(x) for x in row4]

            out_rows.append(row4 + [source["region"]])

    logging.info(
        f'{source["region"]}: pulled {len(out_rows)} rows '
        f'from {source["worksheet"]} ({source["spreadsheet_id"]})'
    )
    return out_rows

def apply_date_format(sh: gspread.Spreadsheet, ws: gspread.Worksheet):
    """
    Форматирует колонки A и C (начиная со 2-й строки) как DATE dd.mm.yyyy
    """
    pattern = TARGET["date_pattern"]
    requests = [
        {
            "repeatCell": {
                "range": {
                    "sheetId": ws.id,
                    "startRowIndex": 1,      # row 2
                    "startColumnIndex": 0,   # A
                    "endColumnIndex": 1
                },
                "cell": {
                    "userEnteredFormat": {
                        "numberFormat": {"type": "DATE", "pattern": pattern}
                    }
                },
                "fields": "userEnteredFormat.numberFormat"
            }
        },
        {
            "repeatCell": {
                "range": {
                    "sheetId": ws.id,
                    "startRowIndex": 1,      # row 2
                    "startColumnIndex": 2,   # C
                    "endColumnIndex": 3
                },
                "cell": {
                    "userEnteredFormat": {
                        "numberFormat": {"type": "DATE", "pattern": pattern}
                    }
                },
                "fields": "userEnteredFormat.numberFormat"
            }
        },
    ]
    api_retry(sh.batch_update, {"requests": requests})

def write_target(gc: gspread.Client, rows: List[List[str]]) -> None:
    sh = api_retry(gc.open_by_key, TARGET["spreadsheet_id"])
    ws = api_retry(sh.worksheet, TARGET["worksheet"])

    # Очищаем только A2:E
    api_retry(ws.batch_clear, [TARGET["clear_range"]])

    if rows:
        # USER_ENTERED -> строки YYYY-MM-DD будут распознаны как даты
        api_retry(
            ws.update,
            range_name=TARGET["range_start"],
            values=rows,
            value_input_option="USER_ENTERED"
        )

    # Применяем формат дат к A и C
    apply_date_format(sh, ws)

    logging.info(f"Target updated: {len(rows)} rows written into A2:E (A,C as DATE)")

def main():
    gc = get_client()

    all_rows: List[List[str]] = []
    for src in SOURCES:
        all_rows.extend(read_source_rows(gc, src))

    write_target(gc, all_rows)
    logging.info("Done ✅")

if __name__ == "__main__":
    main()
