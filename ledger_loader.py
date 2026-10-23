"""
ledger_loader.py

Builds the full ledger: the base Ledger.csv export plus every CSV in the
append folder, standardized to one schema with CreatedAt as a datetime.

Usage from another script or notebook:
    from ledger_loader import get_final_ledger
    ledger = get_final_ledger()
"""

import warnings
from pathlib import Path

import pandas as pd

# ---- Configuration ---------------------------------------------------------
BASE_LEDGER_PATH = Path(r"C:\Users\Administrator\Videos\led\Ledger.csv")
APPEND_FOLDER = Path(r"C:\Users\Administrator\Videos\zynix_led_append")

BASE_DATE_FORMAT = "%d %b %Y %H:%M:%S"

# Raw append-file column -> standard ledger column
APPEND_COLUMN_MAP = {
    "id": "SLNo.",
    "date_time": "CreatedAt",
    "client_id": "ClientID",
    "member_id": "MemberID",
    "ledger_type": "LedgerType",
    "bill_id": "BillId",
    "narration": "Narration",
    "debit": "Debit",
    "credit": "Credit",
    "balance": "Balance",
    "prev_balance": "PreviousBalance",
}

FINAL_COLUMNS = ("ClientID", "CreatedAt", "LedgerType", "Debit", "Credit", "Balance")


# ---- Loaders ---------------------------------------------------------------
def load_base_ledger(path=BASE_LEDGER_PATH) -> pd.DataFrame:
    """Read the base Ledger.csv and parse CreatedAt."""
    df = pd.read_csv(path)
    df["CreatedAt"] = pd.to_datetime(df["CreatedAt"], format=BASE_DATE_FORMAT, errors="coerce")
    return df


def load_append_files(folder=APPEND_FOLDER) -> pd.DataFrame:
    """Read every CSV in the append folder, rename to the standard schema, parse CreatedAt."""
    files = sorted(Path(folder).glob("*.csv"))
    if not files:
        warnings.warn(f"No CSV files found in {folder}")
        return pd.DataFrame(columns=list(APPEND_COLUMN_MAP.values()))

    df = pd.concat((pd.read_csv(f) for f in files), ignore_index=True)

    missing = set(APPEND_COLUMN_MAP) - set(df.columns)
    if missing:
        raise KeyError(f"Append files are missing columns: {sorted(missing)}")

    df = df[list(APPEND_COLUMN_MAP)].rename(columns=APPEND_COLUMN_MAP)

    # format="mixed" (pandas 2+) parses each row on its own, so a file mixing
    # "2026-10-05 09:30:15" and "2026-10-05 09:30:15.123" doesn't produce NaT.
    fmt = {"format": "mixed"} if int(pd.__version__.split(".")[0]) >= 2 else {}
    created = pd.to_datetime(df["CreatedAt"], errors="coerce", **fmt)
    if created.dt.tz is not None:
        created = created.dt.tz_localize(None)  # keep wall-clock time, drop timezone
    df["CreatedAt"] = created.dt.floor("s")      # match base ledger's second precision
    return df


# ---- Main entry point ------------------------------------------------------
def get_final_ledger(
    base_path=BASE_LEDGER_PATH,
    append_folder=APPEND_FOLDER,
    columns=FINAL_COLUMNS,
    only_new_appends=False,
) -> pd.DataFrame:
    """
    Return the combined ledger (base + appends).

    columns          : columns to keep; pass None to keep every column.
    only_new_appends : if True, drop appended rows at or before the base
                       ledger's latest CreatedAt (guards against overlap).
    """
    base = load_base_ledger(base_path)
    appends = load_append_files(append_folder)

    if only_new_appends and not appends.empty:
        appends = appends[appends["CreatedAt"] > base["CreatedAt"].max()]

    frames = [f for f in (base, appends) if not f.empty] or [base]
    final = pd.concat(frames, ignore_index=True)

    if columns is not None:
        final = final[list(columns)]

    n_bad = final["CreatedAt"].isna().sum()
    if n_bad:
        warnings.warn(f"{n_bad} rows have an unparseable CreatedAt (stored as NaT)")

    return final


if __name__ == "__main__":
    ledger = get_final_ledger()
    print("Latest CreatedAt:", ledger["CreatedAt"].max())
    print("Shape:", ledger.shape)
    print(ledger.head())
