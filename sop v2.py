"""
call_list_report.py

Builds the P1-P4 call lists from the trading-customers export and counts them per
manager (TL) and per agent (CRE).

    In a notebook:   from call_list_report import run
                     result = run()
                     result.by_manager

    In a terminal:   python call_list_report.py
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

# ============================================================
# 1. SETTINGS: change these, not the code below
# ============================================================

DOWNLOADS = Path(r"C:\Users\Administrator\Downloads")
FILE_PATTERN = "trading-customers*.csv"        # the newest matching file is used
OUTPUT_FILE = DOWNLOADS / "Call_List_Report_{date}.xlsx"

COLUMNS = {                                    # export column -> name used in the code
    "Client ID": "client_id",
    "Real-Time Status": "status",
    "Manager": "manager",
    "Assigned To": "agent",
    "Last Transaction": "last_txn",
    "Last Call": "last_call",
}

DATA_TZ = "UTC"                 # time zone the export's timestamps are recorded in
REPORT_TZ = "Asia/Kolkata"      # days are counted on this calendar, like the SQL call lists

PRIORITY = {
    "Active": "P1",
    "Inactive": "P2",
    "Sleeping": "P3",
    "Stale": "P3",
    "Lost Lead": "P4",
    "Dormant": "P4",
}
PRIORITIES = ["P1", "P2", "P3", "P4"]

RECENT_DAYS = 2                 # traded or called fewer than this many days ago -> not on the list
CALL_GAP = {"P1": None, "P2": 4, "P3": 4, "P4": 4}   # last call must be MORE than this many days ago
INCLUDE_NEVER_CALLED = True     # clients with no call at all count as "not called recently"
NO_OWNER = "No owner"           # label for a blank manager or agent


# ============================================================
# 2. RESULT
# ============================================================

@dataclass
class Report:
    as_of: pd.Timestamp
    source: Path
    call_list: pd.DataFrame
    by_manager: pd.DataFrame
    by_agent: pd.DataFrame
    checks: dict = field(default_factory=dict)


# ============================================================
# 3. LOADING
# ============================================================

def find_latest_export(folder: Path = DOWNLOADS, pattern: str = FILE_PATTERN) -> Path:
    """The most recently saved file matching the pattern."""
    files = sorted(folder.glob(pattern), key=lambda f: f.stat().st_mtime)
    if not files:
        raise FileNotFoundError(f"No file matching {pattern!r} in {folder}")
    return files[-1]


def load_customers(path: Path, checks: dict) -> pd.DataFrame:
    """Read the export, keep and rename the needed columns, clean text, drop duplicate clients."""
    header = pd.read_csv(path, nrows=0).columns
    missing = [c for c in COLUMNS if c not in header]
    if missing:
        raise ValueError(f"{path.name} is missing columns: {missing}")

    df = pd.read_csv(path, usecols=list(COLUMNS)).rename(columns=COLUMNS)
    for col in ["client_id", "status", "manager", "agent"]:
        df[col] = df[col].astype("string").str.strip()

    checks["rows_in_file"] = len(df)
    checks["duplicate_clients_dropped"] = int(df["client_id"].duplicated().sum())
    return df.drop_duplicates("client_id", keep="first")


# ============================================================
# 4. DATES
# ============================================================

def days_since(dates: pd.Series, as_of: pd.Timestamp) -> pd.Series:
    """Whole calendar days from each date to as_of, counted in REPORT_TZ. Blank stays blank."""
    d = pd.to_datetime(dates, format="ISO8601", errors="coerce", utc=False)
    d = d.dt.tz_localize(DATA_TZ) if d.dt.tz is None else d
    d = d.dt.tz_convert(REPORT_TZ)
    return (as_of.normalize() - d.dt.normalize()).dt.days.astype("Int64")


def add_day_counts(df: pd.DataFrame, as_of: pd.Timestamp, checks: dict) -> pd.DataFrame:
    out = df.copy()
    for col in ["last_txn", "last_call"]:
        raw = out[col]
        out[f"days_since_{col}"] = days_since(raw, as_of)
        unreadable = raw.notna() & out[f"days_since_{col}"].isna()
        checks[f"unreadable_{col}"] = int(unreadable.sum())     # text that isn't a date
    return out


# ============================================================
# 5. RULES
# ============================================================

def assign_priority(df: pd.DataFrame, checks: dict) -> pd.DataFrame:
    out = df.assign(priority=df["status"].map(PRIORITY))
    unknown = out.loc[out["priority"].isna(), "status"].value_counts(dropna=False)
    checks["unknown_statuses"] = unknown.to_dict()                  # e.g. {'Churned': 12}
    return out


def build_call_list(df: pd.DataFrame, checks: dict) -> pd.DataFrame:
    """Who to call: not traded or called recently, and (for P2-P4) not called for CALL_GAP days."""
    txn, call = df["days_since_last_txn"], df["days_since_last_call"]
    recent = txn.lt(RECENT_DAYS).fillna(False) | call.lt(RECENT_DAYS).fillna(False)

    gap = df["priority"].map(CALL_GAP).astype("Float64")            # <NA> means no gap rule
    never_called = call.isna()
    waited = call.gt(gap).fillna(False)
    gap_ok = gap.isna() | waited | (never_called & INCLUDE_NEVER_CALLED)

    keep = df["priority"].notna() & ~recent & gap_ok
    checks["never_called_on_list"] = int((keep & never_called).sum())
    return df[keep].copy()


# ============================================================
# 6. SUMMARIES
# ============================================================

def count_by(call_list: pd.DataFrame, owner_col: str) -> pd.DataFrame:
    """Cases per owner and priority, with totals."""
    owners = call_list[owner_col].fillna(NO_OWNER)
    table = pd.crosstab(owners, call_list["priority"], margins=True, margins_name="Total")
    table = table.reindex(columns=PRIORITIES + ["Total"], fill_value=0)
    table.index.name = owner_col.replace("_", " ").title()
    body = table.drop(index="Total").sort_values("Total", ascending=False)
    return pd.concat([body, table.loc[["Total"]]])


# ============================================================
# 7. RUN
# ============================================================

def run(path: Path | str | None = None, as_of: str | pd.Timestamp | None = None,
        save: bool = False, verbose: bool = True) -> Report:
    """Load, calculate, apply the rules and summarise. as_of defaults to now (REPORT_TZ)."""
    checks: dict = {}
    path = Path(path) if path else find_latest_export()
    if as_of is None:
        as_of = pd.Timestamp.now(tz=REPORT_TZ)
    else:
        as_of = pd.Timestamp(as_of)
        as_of = as_of.tz_localize(REPORT_TZ) if as_of.tzinfo is None else as_of.tz_convert(REPORT_TZ)

    customers = load_customers(path, checks)
    customers = add_day_counts(customers, as_of, checks)
    customers = assign_priority(customers, checks)
    call_list = build_call_list(customers, checks)

    report = Report(as_of=as_of, source=path, call_list=call_list,
                    by_manager=count_by(call_list, "manager"),
                    by_agent=count_by(call_list, "agent"), checks=checks)
    if verbose:
        print_checks(report)
    if save:
        save_report(report)
    return report


def print_checks(report: Report) -> None:
    c = report.checks
    print(f"Source: {report.source.name} | as of {report.as_of:%d %b %Y %H:%M} ({REPORT_TZ})")
    print(f"Rows in file: {c['rows_in_file']} | duplicate clients dropped: "
          f"{c['duplicate_clients_dropped']}")
    print(f"Unreadable dates - last transaction: {c['unreadable_last_txn']} | "
          f"last call: {c['unreadable_last_call']}")
    print(f"Statuses with no priority (left out): {c['unknown_statuses'] or 'none'}")
    print(f"On the call list: {len(report.call_list)} "
          f"(never called: {c['never_called_on_list']})")


def save_report(report: Report) -> Path:
    path = Path(str(OUTPUT_FILE).format(date=f"{report.as_of:%Y-%m-%d}"))
    with pd.ExcelWriter(path) as writer:
        report.by_manager.to_excel(writer, sheet_name="By manager")
        report.by_agent.to_excel(writer, sheet_name="By agent")
        report.call_list.to_excel(writer, sheet_name="Call list", index=False)
    print("Saved:", path)
    return path


if __name__ == "__main__":
    run(save=True)
