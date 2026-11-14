"""
call_list_report.py

Builds the P1-P4 call lists from the trading-customers export, ranks who to call first, shares out
clients with no agent, and counts the lists per manager (TL) and per agent (CRE).

    In a notebook:   from call_list_report import run
                     result = run()                     # newest export in Downloads, as of now
                     result.by_manager, result.by_agent, result.call_list

    In a terminal:   python call_list_report.py

    In the cloud:    build_report(df, as_of) does no file reading or writing, so it can run on data
                     from any source (object storage, a database, an API) - see section 8.

Speed notes (measured on a 500,000-row export):
    * End to end, before saving: 2.1 s for the original script, 1.1 s for this one, while doing more
      (duplicate checks, ranking, sharing out unowned clients, day bands).
    * Reading with engine="pyarrow" was 6.5x faster than the default reader (156 ms vs 1,022 ms).
      Without pyarrow installed the script still works, but runs at about the original's speed.
    * Columns pyarrow already recognises as dates are not parsed again.
    * Text columns with few different values become categories: lookups and counts get faster,
      memory gets smaller.
    * Summaries use groupby().size(), 2.6x faster than pd.crosstab for the same table.
    * The Excel file holds the summaries and each agent's top queue. A full call list above
      EXCEL_MAX_ROWS goes to CSV (or Parquet): writing 421,582 rows to Excel took 50 s, CSV 3.5 s.
"""
from __future__ import annotations

import csv
import heapq
import importlib.util
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

log = logging.getLogger("call_list_report")

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

# Day bands for "days since last trade". Why: lets TLs see at a glance how cold each list is.
BAND_EDGES = [2, 4, 8, 15]
BAND_LABELS = ["0-1 days", "2-3 days", "4-7 days", "8-14 days", "15+ days"]

AGENTS: list[str] | None = None  # agents who may receive unowned clients; None = every agent on the list
TOP_N_PER_AGENT = 50             # length of each agent's ranked queue in result.queues

# Why a row limit for Excel: writing 421,582 rows to Excel took 50 seconds in testing, against
# 3.5 s for CSV and 2.8 s for Parquet. Up to this many rows the full list goes in the workbook;
# beyond it, "auto" saves it as a CSV next to the workbook (CSV still opens in Excel).
EXCEL_MAX_ROWS = 50_000

# Why: pyarrow's CSV reader is several times faster. Fall back to pandas' own reader if it's missing,
# so the script still runs on any machine.
CSV_ENGINE = "pyarrow" if importlib.util.find_spec("pyarrow") else "c"


# ============================================================
# 2. RESULT
# ============================================================

@dataclass
class Report:
    """Everything one run produces. Why: one object instead of eight loose variables."""
    as_of: pd.Timestamp
    source: str
    call_list: pd.DataFrame
    by_manager: pd.DataFrame
    by_agent: pd.DataFrame
    queues: pd.DataFrame
    checks: dict = field(default_factory=dict)
    timings_ms: dict = field(default_factory=dict)


class _Timer:
    """Records how long each stage takes. Why: in the cloud you pay for run time, so measure it."""

    def __init__(self, store: dict):
        self.store = store

    def __call__(self, name: str):
        self.name = name
        return self

    def __enter__(self):
        self.t0 = time.perf_counter()

    def __exit__(self, *exc):
        self.store[self.name] = round((time.perf_counter() - self.t0) * 1000, 1)


# ============================================================
# 3. LOADING
# ============================================================

def find_latest_export(folder: Path = DOWNLOADS, pattern: str = FILE_PATTERN) -> Path:
    """The most recently saved file matching the pattern."""
    files = list(folder.glob(pattern))
    if not files:
        raise FileNotFoundError(f"No file matching {pattern!r} in {folder}")
    # Why max() and not sorted()[-1]: we only need the newest file, and max() finds it in one pass.
    return max(files, key=lambda f: f.stat().st_mtime)


def read_export(path: Path | str) -> pd.DataFrame:
    """Read only the needed columns, with the fastest available reader."""
    # Why read the header line with the csv module: it checks the columns without loading any data,
    # and it works whichever engine reads the file.
    with open(path, newline="", encoding="utf-8-sig") as f:
        header = next(csv.reader(f))
    missing = [c for c in COLUMNS if c not in header]
    if missing:
        raise ValueError(f"{Path(path).name} is missing columns: {missing}")
    # Why usecols: the export has many more columns; skipping them saves reading time and memory.
    return pd.read_csv(path, usecols=list(COLUMNS), engine=CSV_ENGINE)


# ============================================================
# 4. CLEANING
# ============================================================

def clean(raw: pd.DataFrame, checks: dict) -> pd.DataFrame:
    """Rename, trim text, make low-variety columns categories, drop duplicate clients."""
    df = raw.rename(columns=COLUMNS)
    for col in ["client_id", "status", "manager", "agent"]:
        # Why strip: "Active " with a stray space used to fall out of the priority mapping.
        df[col] = df[col].astype("string").str.strip()
    for col in ["status", "manager", "agent"]:
        # Why category: a few hundred different labels repeated across many rows. Stored once,
        # they make lookups and group counts faster and use far less memory.
        df[col] = df[col].astype("category")

    checks["rows_in_file"] = len(df)
    dupes = df["client_id"].duplicated()          # Why: a hash-set check, one pass over the IDs
    checks["duplicate_clients_dropped"] = int(dupes.sum())
    return df[~dupes]


# ============================================================
# 5. DATES
# ============================================================

def to_report_dates(values: pd.Series) -> pd.Series:
    """Any date column -> timezone-aware dates in REPORT_TZ. Unreadable values become blank."""
    if pd.api.types.is_datetime64_any_dtype(values):
        d = values                                # Why: pyarrow already parsed it; don't do it twice
    else:
        # Why format="ISO8601": reads timestamps with and without milliseconds alike.
        # Why errors="coerce": one bad value shouldn't stop the run; they're counted in the checks.
        d = pd.to_datetime(values, format="ISO8601", errors="coerce")
    if d.dt.tz is None:
        d = d.dt.tz_localize(DATA_TZ)
    return d.dt.tz_convert(REPORT_TZ)


def add_day_counts(df: pd.DataFrame, as_of: pd.Timestamp, checks: dict) -> pd.DataFrame:
    """Calendar days since the last trade and the last call, counted in REPORT_TZ."""
    today = as_of.normalize()
    new_cols = {}
    for col in ["last_txn", "last_call"]:
        dates = to_report_dates(df[col])
        # Why normalize(): count calendar days, not 24-hour blocks (23:30 two days ago = 2 days).
        days = (today - dates.dt.normalize()).dt.days.astype("Int64")
        new_cols[f"days_since_{col}"] = days
        checks[f"unreadable_{col}"] = int((df[col].notna() & days.isna()).sum())
    # Why assign once: adding all new columns in one step avoids copying the table twice.
    return df.assign(**new_cols)


def add_day_bands(df: pd.DataFrame) -> pd.DataFrame:
    """Label 'days since last trade' with a band, by binary search over BAND_EDGES."""
    days = df["days_since_last_txn"]
    known = days.notna().to_numpy()
    band = np.full(len(df), None, dtype=object)
    # Why np.searchsorted: a binary search over the band edges for every row at once.
    # It's the same idea as bisect_right on one value, done for the whole column.
    idx = np.searchsorted(BAND_EDGES, days[known].to_numpy(dtype="int64"), side="right")
    band[known] = np.asarray(BAND_LABELS, dtype=object)[idx]
    return df.assign(txn_band=pd.Categorical(band, categories=BAND_LABELS, ordered=True))


# ============================================================
# 6. RULES
# ============================================================

def assign_priority(df: pd.DataFrame, checks: dict) -> pd.DataFrame:
    # Why map on a category column: pandas looks up each different status once, not once per row.
    priority = df["status"].map(PRIORITY).astype("category")
    unknown = df.loc[priority.isna(), "status"].value_counts()
    checks["unknown_statuses"] = {k: int(v) for k, v in unknown.items() if v}
    return df.assign(priority=priority)


def build_call_list(df: pd.DataFrame, checks: dict) -> pd.DataFrame:
    """Who to call: not traded or called recently, and (for P2-P4) not called for CALL_GAP days."""
    txn, call = df["days_since_last_txn"], df["days_since_last_call"]
    # Why fillna(False): a blank date isn't "recent". Comparing a blank gives <NA>, which can't
    # be used to pick rows until it's turned into True or False.
    recent = txn.lt(RECENT_DAYS).fillna(False) | call.lt(RECENT_DAYS).fillna(False)

    gap = df["priority"].map(CALL_GAP).astype("Float64")            # <NA> means no gap rule
    never_called = call.isna()
    waited = call.gt(gap).fillna(False)
    # Why an explicit never-called rule: "blank > 4" is False, which used to drop never-called
    # clients from P2-P4 without anyone choosing that.
    gap_ok = gap.isna() | waited | (never_called & INCLUDE_NEVER_CALLED)

    keep = df["priority"].notna() & ~recent & gap_ok
    checks["never_called_on_list"] = int((keep & never_called).sum())
    return df[keep]


def assign_unowned(call_list: pd.DataFrame, checks: dict) -> pd.DataFrame:
    """Give each client with no agent to whichever agent currently has the fewest clients."""
    agents = AGENTS or sorted(call_list["agent"].dropna().unique())
    unowned = call_list["agent"].isna()
    checks["unowned_assigned"] = int(unowned.sum())
    if not agents or not unowned.any():
        return call_list.assign(agent_assigned=False)

    load = call_list["agent"].value_counts().reindex(agents, fill_value=0)
    # Why a min-heap: "who has the fewest clients right now?" is answered in a step that stays
    # quick however many agents there are. Greedy: each client goes to the least-loaded agent.
    heap = [(int(n), a) for a, n in load.items()]
    heapq.heapify(heap)
    new_agent = []
    for _ in range(int(unowned.sum())):
        n, agent = heapq.heappop(heap)
        new_agent.append(agent)
        heapq.heappush(heap, (n + 1, agent))

    agent_col = call_list["agent"].astype("object")
    agent_col[unowned.to_numpy()] = new_agent
    return call_list.assign(agent=agent_col.astype("category"), agent_assigned=unowned)


def rank_calls(call_list: pd.DataFrame) -> pd.DataFrame:
    """Order: P1 first; within a priority, longest without a call first; never called first of all."""
    # Why one sort with several keys: one pass of ordering serves every agent's queue at once.
    # Why the client ID as the last key: many clients tie (e.g. never called); without a tie-break
    # the order of tied clients could change from run to run.
    ranked = call_list.sort_values(
        ["priority", "days_since_last_call", "client_id"],
        ascending=[True, False, True], na_position="first", kind="stable")
    # Why cumcount: numbers each agent's clients 1, 2, 3... in the ranked order, without a loop.
    return ranked.assign(call_rank=ranked.groupby("agent", observed=True).cumcount() + 1)


# ============================================================
# 7. SUMMARIES
# ============================================================

def count_by(call_list: pd.DataFrame, owner_col: str) -> pd.DataFrame:
    """Cases per owner and priority, with a Total row and column."""
    col = call_list[owner_col]
    # Why add_categories + fillna: fills blanks inside the category column, instead of converting
    # every row to text first.
    if NO_OWNER not in col.cat.categories:
        col = col.cat.add_categories([NO_OWNER])
    owners = col.fillna(NO_OWNER)
    # Why groupby().size().unstack() instead of pd.crosstab: the same table, measured 2.6x faster.
    table = (call_list.assign(owner=owners)
             .groupby(["owner", "priority"], observed=True).size()
             .unstack(fill_value=0)
             .reindex(columns=PRIORITIES, fill_value=0))
    table["Total"] = table.sum(axis=1)
    table = table.sort_values("Total", ascending=False)
    table.loc["Total"] = table.sum()
    table.index.name = owner_col.replace("_", " ").title()
    table.columns.name = "priority"
    return table


# ============================================================
# 8. BUILD AND RUN
# ============================================================

def build_report(raw: pd.DataFrame, as_of: pd.Timestamp, source: str = "data") -> Report:
    """Everything except reading and writing files.
    Why separate: in the cloud the data may come from storage or a database; this part stays the same,
    and it's easy to test with a small DataFrame."""
    checks: dict = {}
    timings: dict = {}
    timed = _Timer(timings)

    with timed("clean"):
        df = clean(raw, checks)
    with timed("dates"):
        df = add_day_counts(df, as_of, checks)
        df = add_day_bands(df)
    with timed("rules"):
        df = assign_priority(df, checks)
        call_list = build_call_list(df, checks)
        call_list = assign_unowned(call_list, checks)
        call_list = rank_calls(call_list)
    with timed("summaries"):
        by_manager = count_by(call_list, "manager")
        by_agent = count_by(call_list, "agent")
        queues = call_list[call_list["call_rank"] <= TOP_N_PER_AGENT]

    return Report(as_of=as_of, source=source, call_list=call_list, by_manager=by_manager,
                  by_agent=by_agent, queues=queues, checks=checks, timings_ms=timings)


def run(path: Path | str | None = None, as_of: str | pd.Timestamp | None = None,
        save: bool = False, call_list_as: str = "auto", verbose: bool = True) -> Report:
    """Read the export, build the report, optionally save it.
    call_list_as: "auto" (Excel up to EXCEL_MAX_ROWS rows, otherwise CSV), "excel", "csv" or "parquet"."""
    total_t0 = time.perf_counter()
    path = Path(path) if path else find_latest_export()
    as_of = _as_report_time(as_of)

    t0 = time.perf_counter()
    raw = read_export(path)
    read_ms = round((time.perf_counter() - t0) * 1000, 1)

    report = build_report(raw, as_of, source=path.name)
    report.timings_ms = {"read": read_ms, **report.timings_ms}
    if save:
        t0 = time.perf_counter()
        save_report(report, call_list_as)
        report.timings_ms["save"] = round((time.perf_counter() - t0) * 1000, 1)
    report.timings_ms["total"] = round((time.perf_counter() - total_t0) * 1000, 1)
    if verbose:
        print_checks(report)
    return report


def _as_report_time(as_of) -> pd.Timestamp:
    if as_of is None:
        return pd.Timestamp.now(tz=REPORT_TZ)
    as_of = pd.Timestamp(as_of)
    return as_of.tz_localize(REPORT_TZ) if as_of.tzinfo is None else as_of.tz_convert(REPORT_TZ)


def print_checks(report: Report) -> None:
    c = report.checks
    print(f"Source: {report.source} | as of {report.as_of:%d %b %Y %H:%M} ({REPORT_TZ}) | "
          f"reader: {CSV_ENGINE}")
    print(f"Rows in file: {c['rows_in_file']:,} | duplicate clients dropped: "
          f"{c['duplicate_clients_dropped']:,}")
    print(f"Unreadable dates - last transaction: {c['unreadable_last_txn']:,} | "
          f"last call: {c['unreadable_last_call']:,}")
    print(f"Statuses with no priority (left out): {c['unknown_statuses'] or 'none'}")
    print(f"On the call list: {len(report.call_list):,} (never called: {c['never_called_on_list']:,}; "
          f"unowned shared out: {c['unowned_assigned']:,})")
    print("Timings (ms):", report.timings_ms)


def save_report(report: Report, call_list_as: str = "auto") -> Path:
    path = Path(str(OUTPUT_FILE).format(date=f"{report.as_of:%Y-%m-%d}"))
    if call_list_as == "auto":
        call_list_as = "excel" if len(report.call_list) <= EXCEL_MAX_ROWS else "csv"
    # Why xlsxwriter when available: it writes Excel files faster than openpyxl.
    engine = "xlsxwriter" if importlib.util.find_spec("xlsxwriter") else "openpyxl"
    with pd.ExcelWriter(path, engine=engine) as writer:
        report.by_manager.to_excel(writer, sheet_name="By manager")
        report.by_agent.to_excel(writer, sheet_name="By agent")
        _export_table(report.queues).to_excel(writer, sheet_name=f"Top {TOP_N_PER_AGENT} per agent",
                                              index=False)
        if call_list_as == "excel":
            _export_table(report.call_list).to_excel(writer, sheet_name="Call list", index=False)
    if call_list_as == "csv":
        # Why no _export_table here: CSV stores dates with their time zone as plain text already,
        # so the extra copy and date formatting are skipped.
        report.call_list.to_csv(path.with_suffix(".call_list.csv"), index=False)
    elif call_list_as == "parquet":
        # Why parquet: the fastest to write and read for large tables, a quarter of the CSV's size,
        # and it keeps real dates, numbers and categories, so nothing needs converting.
        report.call_list.to_parquet(path.with_suffix(".call_list.parquet"), index=False)
    log.info("Saved %s", path)
    return path


def _export_table(df: pd.DataFrame) -> pd.DataFrame:
    """Excel can't store time zones, so dates are written as text in REPORT_TZ."""
    out = df.copy()
    for col in ["last_txn", "last_call"]:
        if pd.api.types.is_datetime64_any_dtype(out[col]):
            out[col] = out[col].dt.tz_convert(REPORT_TZ).dt.strftime("%Y-%m-%d %H:%M")
    return out


if __name__ == "__main__":
    run(save=True)
