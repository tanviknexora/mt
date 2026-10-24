"""
ledger_loader.py  (Polars version)

Builds the full ledger: the base Ledger.csv export plus every CSV in the
append folder, standardized to one schema with CreatedAt as a datetime.

Requires polars >= 1.0 (plus pyarrow if you call it with as_pandas=True).

Usage from another script or notebook:
    from ledger_loader import get_final_ledger
    ledger = get_final_ledger()                   # polars DataFrame
    ledger_pd = get_final_ledger(as_pandas=True)  # pandas DataFrame, for existing pandas code
"""

import warnings
from pathlib import Path

import polars as pl

# ---- Configuration ---------------------------------------------------------
BASE_LEDGER_PATH = Path(r"C:\Users\Administrator\Videos\led\Ledger.csv")
APPEND_FOLDER = Path(r"C:\Users\Administrator\Videos\zynix_led_append")

BASE_DATE_FORMAT = "%d %b %Y %H:%M:%S"    # e.g. "05 Oct 2026 09:30:15"
APPEND_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"  # applied to the first 19 chars, see below

# Rows Polars samples to guess each column's type. If you ever get an error like
# "could not parse `ABC12` as dtype i64", raise this (None = scan the whole file).
INFER_ROWS = 10_000

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


# ---- Loaders (lazy: nothing is read until .collect()) ----------------------
def scan_base_ledger(path=BASE_LEDGER_PATH) -> pl.LazyFrame:
    """Lazily read the base Ledger.csv and parse CreatedAt."""
    return pl.scan_csv(path, infer_schema_length=INFER_ROWS).with_columns(
        pl.col("CreatedAt")
        .str.strip_chars()
        .str.to_datetime(BASE_DATE_FORMAT, time_unit="us", strict=False)
    )


def scan_append_files(folder=APPEND_FOLDER) -> pl.LazyFrame | None:
    """Lazily read every CSV in the append folder, rename to the standard schema, parse CreatedAt."""
    files = sorted(Path(folder).glob("*.csv"))
    if not files:
        warnings.warn(f"No CSV files found in {folder}")
        return None

    # One scan per file, combined with diagonal_relaxed: files are read in
    # parallel, and it tolerates files whose column order or inferred types
    # differ (e.g. debit read as int in one file and float in another).
    lf = pl.concat(
        [pl.scan_csv(f, infer_schema_length=INFER_ROWS) for f in files],
        how="diagonal_relaxed",
    )

    missing = set(APPEND_COLUMN_MAP) - set(lf.collect_schema().names())
    if missing:
        raise KeyError(f"Append files are missing columns: {sorted(missing)}")

    # Turns "2026-10-05 09:30:15", "2026-10-05 09:30:15.123" or
    # "2026-10-05T09:30:15.123+04:00" into "2026-10-05 09:30:15" before parsing.
    # Cutting the fraction floors to the second and cutting the offset keeps the
    # wall-clock time, matching the pandas version. Anything that isn't
    # YYYY-MM-DD HH:MM:SS at the start becomes null (and triggers the warning).
    created = (
        pl.col("date_time")
        .cast(pl.String)
        .str.strip_chars()
        .str.replace("T", " ", literal=True)
        .str.slice(0, 19)
        .str.to_datetime(APPEND_DATE_FORMAT, time_unit="us", strict=False)
    )

    return lf.select(
        (created if src == "date_time" else pl.col(src)).alias(dst)
        for src, dst in APPEND_COLUMN_MAP.items()
    )


# ---- Main entry point ------------------------------------------------------
def get_final_ledger(
    base_path=BASE_LEDGER_PATH,
    append_folder=APPEND_FOLDER,
    columns=FINAL_COLUMNS,
    only_new_appends=False,
    as_pandas=False,
):
    """
    Return the combined ledger (base + appends).

    columns          : columns to keep; pass None to keep every column.
                       Unused columns (e.g. Narration) are never parsed.
    only_new_appends : if True, drop appended rows at or before the base
                       ledger's latest CreatedAt (guards against overlap).
    as_pandas        : if True, return a pandas DataFrame instead of polars.
    """
    base = scan_base_ledger(base_path).with_columns(_is_base=pl.lit(True))
    appends = scan_append_files(append_folder)

    frames = [base]
    if appends is not None:
        frames.append(appends.with_columns(_is_base=pl.lit(False)))
    final = pl.concat(frames, how="diagonal_relaxed")

    if only_new_appends:
        # Keep every base row, and appended rows newer than the base's latest
        # CreatedAt. Done in the same pass, so the base file is read only once.
        base_max = pl.col("CreatedAt").filter(pl.col("_is_base")).max()
        final = final.filter(pl.col("_is_base") | (pl.col("CreatedAt") > base_max))

    final = final.drop("_is_base")
    if columns is not None:
        final = final.select(list(columns))

    df = final.collect()

    if "CreatedAt" in df.columns:
        n_bad = df["CreatedAt"].null_count()
        if n_bad:
            warnings.warn(f"{n_bad} rows have an unparseable CreatedAt (stored as null)")

    return df.to_pandas() if as_pandas else df


if __name__ == "__main__":
    ledger = get_final_ledger()
    print("Latest CreatedAt:", ledger["CreatedAt"].max())
    print("Shape:", ledger.shape)
    print(ledger.head())