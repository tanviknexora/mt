# Study Notes: The Python, Polars and Design Patterns Behind `ledger_loader.py` and Your Notebooks

`ledger_loader.py` is a lazy Polars ingestion module. It reads a base `Ledger.csv` and every CSV in an append folder, maps both onto one schema, parses `CreatedAt` defensively, and only reads data when `.collect()` runs. Both notebooks fail for an unrelated reason: the kernel can't find the `.py` file. It is not on `sys.path`, so the code itself is not at fault. The fix is a 3-line `sys.path` insert, or moving the file next to the notebooks. These notes teach every concept in the code. They end with templates, exercises, a quiz and an 8-week plan, so you can write code like this without AI help.

**Note on `cohort_analysis.ipynb`:** its contents were not in the chat and I could not read that path. Paste its cells (code plus outputs) and the same treatment can be applied to it. Most of what follows will carry over (pandas/Polars group-bys, date handling, imports).

---

## TL;DR
- **The error is a path problem, not a code problem.** Python only searches the folders listed in `sys.path`. A notebook kernel's search path starts with its own working directory, which is not the folder holding `ledger_loader.py`. Fix it by placing the file beside the notebooks, or with `sys.path.insert(0, r"<folder>")` before the import. Also make sure `polars` (and `pyarrow` for `as_pandas=True`) are installed in *the kernel's* Python. Check that with `sys.executable`.
- **The loader is a textbook ingestion pipeline in five parts:** a config block, then lazy scans (`pl.scan_csv`), then schema standardization (a rename map plus `pl.concat(how="diagonal_relaxed")`), then defensive date parsing (`strict=False` → nulls → count → warn), then a single `.collect()` at the end. Polars' optimizer can then apply projection and predicate pushdown, which is why unused columns are never parsed.
- **To write this yourself, learn in this order:** core Python (functions, comprehensions, truthiness, exceptions), then Polars expressions and contexts (`select`/`with_columns`/`filter`), then lazy evaluation, then design patterns (validation, incremental loads). Practise by rebuilding the loader from the skeletons and exercises below without looking. Pair that with SQL + dbt + git + pytest to move toward analytics engineering.

---

## Key Findings

1. **The `ModuleNotFoundError` means "not on the search path", not "not installed".** Per the Python docs, `sys.path` is built from the directory containing the input script, *or the current directory when no script is given*, then `PYTHONPATH`, then the standard library, then `site-packages`. Jupyter has no input script, so the kernel's working directory (usually the notebook's folder) comes first. `ledger_loader.py` lives elsewhere, so it isn't found. Running `pip install ledger_loader` is wrong: it is your local file, not a PyPI package.
2. **Laziness is the core performance idea.** The Polars user guide says the lazy API defers execution until the query is collected, which lets the planner apply optimizations.\[1\] Predicate pushdown applies filters as early as possible (at scan level). Projection pushdown selects only the columns needed at scan level.\[2\] Your loader builds every step on a `LazyFrame` and calls `.collect()` once.
3. **`diagonal_relaxed` is a deliberate schema-drift tolerance choice.** In the official `pl.concat` docs, `diagonal` "finds a union between the column schemas and fills missing column values with null". The `_relaxed` variants additionally "coerce columns to their common supertype if they are mismatched (eg: Int32 → Int64)".\[3\]\[4\] The trade-off is that a renamed column (e.g. `debit` → `Debit_amt`) silently becomes a new, half-null column.\[5\] The loader's missing-column `KeyError` check is the guard against that, but it covers only the append files.
4. **`strict=False` turns parse failures into nulls.** The Polars docs define `strict` as "Raise an error if any conversion fails", so `False` produces null instead.\[6\]\[7\] That is why the loader counts nulls afterwards and warns. Without the count, bad dates would vanish silently.
5. **One subtle behaviour worth knowing:** with `only_new_appends=True`, appended rows whose `CreatedAt` failed to parse (null) are **silently dropped**. `null > base_max` evaluates to null, and `filter` keeps only `True` rows. They are therefore not counted in the final null warning. See Pitfalls §G.

---

## Details

### PART A: Core Python syntax and logic

#### A1. Docstrings, comments and module layout

```python
"""Module docstring: first string literal in the file. Shown by help(ledger_loader)."""

def scan_base_ledger(path=BASE_LEDGER_PATH) -> pl.LazyFrame:
    """Function docstring: first statement in the function body."""
    ...  # comment: ignored by Python, for humans only
```

- A **docstring** is a string literal placed first in a module, function or class. Python stores it in `__doc__`, and `help()` displays it. A **comment** (`#`) is discarded by the interpreter.
- **Canonical module layout** (the order the loader follows):
  1. Module docstring
  2. Imports: standard library first (`warnings`, `pathlib`), a blank line, then third-party (`polars`)
  3. Configuration constants (`UPPER_CASE`)
  4. Helper functions (`scan_base_ledger`, `scan_append_files`)
  5. Main entry-point function (`get_final_ledger`)
  6. `if __name__ == "__main__":` guard

#### A2. The `if __name__ == "__main__":` guard

The Python docs explain it this way. When a module runs in the "top-level code environment" (e.g. `python ledger_loader.py`), its `__name__` is set to `'__main__'`.\[8\] When it is imported, `__name__` is the module's own name (`'ledger_loader'`).\[9\] So:

```python
if __name__ == "__main__":
    ledger = get_final_ledger()   # runs ONLY for: python ledger_loader.py
    print(ledger.head())          # does NOT run for: from ledger_loader import get_final_ledger
```

**Why it matters for you:** without the guard, every notebook import would load the entire ledger and print it as a side effect. The docs recommend keeping as few statements as possible under the guard. The usual pattern is a `main()` function that the guard calls.\[10\]

#### A3. Import styles and how Python finds modules

| Syntax | What gets bound | Used in your code |
|---|---|---|
| `import warnings` | name `warnings` → module; call `warnings.warn(...)` | ✅ |
| `import polars as pl` | alias `pl` → module | ✅ (also `pandas as pd`, `numpy as np`) |
| `from pathlib import Path` | name `Path` → one object from the module | ✅ |
| `from datetime import datetime, timedelta` | two classes | ✅ notebooks |
| `from ledger_loader import get_final_ledger` | your own function | ✅ notebooks (failing) |

- **Standard library** modules (`os`, `warnings`, `pathlib`, `datetime`, `sys`) ship with Python. **Third-party** ones (`polars`, `pandas`, `numpy`, `pyarrow`) must be installed with pip/conda *into the same environment that runs your code*.
- **Search order**: the Python tutorial says the interpreter first checks built-in modules, then searches the directories in `sys.path` for `spam.py`. `sys.path` is initialized from the script's directory (or the current directory), `PYTHONPATH`, and the installation defaults including `site-packages`. Programs can modify `sys.path` after start-up.\[11\]
- Inspect it yourself:

```python
import sys, os
print(sys.executable)   # WHICH python runs this kernel
print(os.getcwd())      # the kernel's current working directory
print(sys.path[:5])     # first places Python looks
```

#### A4. Constants, raw strings and `pathlib`

```python
BASE_LEDGER_PATH = Path(r"C:\Users\Administrator\Videos\led\Ledger.csv")
```

- **UPPER_CASE** is a naming *convention* (PEP 8) meaning "treat as constant". Python does not enforce it.
- **Raw string `r"..."`**: backslashes are kept literally. In a normal string, `"C:\Users"` makes Python read `\U` as the start of a Unicode escape (`\UXXXXXXXX`), so the line is a **SyntaxError**. Other sequences such as `\n` or `\t` silently become newline or tab. Alternatives are forward slashes (`"C:/Users/..."`, which Windows accepts) or doubled backslashes. One gotcha: a raw string cannot end in a single backslash (`r"C:\folder\"` is invalid).
- **`pathlib.Path`** is an object-oriented path. Useful members:

```python
p = Path(r"C:\data\zynix_led_append")
p / "file.csv"           # join paths with /
p.exists(), p.is_dir()
p.name, p.stem, p.suffix # 'zynix_led_append', ..., ''
files = sorted(p.glob("*.csv"))   # all CSVs, in deterministic (alphabetical) order
```

`glob()` yields files in whatever order the filesystem returns them, so `sorted()` makes runs reproducible. `Path(folder)` also lets callers pass either a string or a `Path`.

#### A5. Literals and built-in collections

```python
INFER_ROWS = 10_000          # PEP 515: underscores are ignored, purely for readability
```
PEP 515 allows "one underscore between digits, and after base specifiers". The underscores "have no semantic meaning".\[12\]

| Type | Literal | Mutable? | Ordered? | Duplicates? | Role in loader |
|---|---|---|---|---|---|
| `dict` | `{"id": "SLNo."}` | yes | insertion order | keys unique | `APPEND_COLUMN_MAP` (rename map) |
| `tuple` | `("ClientID", "CreatedAt")` | **no** | yes | yes | `FINAL_COLUMNS` |
| `list` | `[base]` | yes | yes | yes | `frames`, list of scans |
| `set` | `set(...)` | yes | no | no | missing-column check |

Key dict and set idioms used:

```python
for src, dst in APPEND_COLUMN_MAP.items():  # (key, value) pairs
set(APPEND_COLUMN_MAP)                      # iterating a dict yields KEYS -> set of raw names
missing = required - present                # set difference: in required but not in present
```

**Why `FINAL_COLUMNS` is a tuple:** it is used as a *default argument* (A6). Default values are created once when `def` runs, so a mutable default (like a list) can be accidentally modified and the change persists across calls. Tuples are immutable, which makes them safe defaults. `list(columns)` converts the tuple when Polars needs a list.

#### A6. Functions: defaults, keywords, flags, returns

```python
def get_final_ledger(base_path=BASE_LEDGER_PATH, append_folder=APPEND_FOLDER,
                     columns=FINAL_COLUMNS, only_new_appends=False, as_pandas=False):
```

- **Default arguments** make every parameter optional, so `get_final_ledger()` just works.
- **Keyword arguments** at call time make calls self-documenting: `get_final_ledger(as_pandas=True, columns=None)`.
- **Boolean flags** (`only_new_appends`, `as_pandas`) switch behaviour on or off.
- **`None` as a sentinel**: `columns=None` means "keep everything".
- **Early return / guard clause**: `scan_append_files` returns `None` immediately if there are no files. That keeps the main path un-nested.
- **Keyword-only parameters**: in docs you will see signatures like `polars.concat(items, *, how='vertical', ...)`. Everything after `*` **must** be passed by keyword (`how="diagonal_relaxed"`). Learn to read this, because it is in every API reference.

#### A7. Type hints and PEP 604 unions

```python
def scan_append_files(folder=APPEND_FOLDER) -> pl.LazyFrame | None:
```

- `-> X` annotates the return type. Hints are **not enforced** at runtime; they serve readers, IDE autocomplete and checkers (mypy, pyright).
- `X | None` is PEP 604 syntax (Python 3.10+) for "either X or None". It is equivalent to `typing.Union[X, None]` / `Optional[X]`.\[13\] The docs show `def square(number: int | float) -> int | float:`.\[14\]
- The hint signals that callers must handle `None`, which `get_final_ledger` does (`if appends is not None`).

#### A8. Comprehensions, generators, unpacking, ternaries

```python
# List comprehension -> builds a full list
scans = [pl.scan_csv(f, infer_schema_length=INFER_ROWS) for f in files]

# Generator expression passed directly as the ONLY argument (no extra parentheses needed)
lf.select(
    (created if src == "date_time" else pl.col(src)).alias(dst)
    for src, dst in APPEND_COLUMN_MAP.items()
)
```

Reading the second one from inside out:
- `for src, dst in ....items()` is **tuple unpacking**: each `(key, value)` pair is split into two names.
- `created if src == "date_time" else pl.col(src)` is a **conditional (ternary) expression**: `A if condition else B`.
- `.alias(dst)` renames the result to the standard name.
- The whole thing is equivalent to this loop:

```python
exprs = []
for src, dst in APPEND_COLUMN_MAP.items():
    if src == "date_time":
        exprs.append(created.alias(dst))
    else:
        exprs.append(pl.col(src).alias(dst))
lf.select(exprs)
```

Practise translating loop ⇄ comprehension in both directions until it's automatic.

#### A9. f-strings, truthiness, `is not None`

```python
f"No CSV files found in {folder}"
f"Append files are missing columns: {sorted(missing)}"
```
Anything inside `{}` is evaluated. Format specs also work: `f"{n_bad:,}"` → `1,234`.

**Truthiness**: empty containers, `0`, `0.0`, `""` and `None` are *falsy*; most other things are truthy.

| Code | Means |
|---|---|
| `if not files:` | list is empty |
| `if missing:` | set is non-empty |
| `if n_bad:` | count > 0 |

**`is not None` vs `!= None`**: `is` tests *identity* (the same object), and there is exactly one `None`. PEP 8 says comparisons to singletons like `None` should use `is` / `is not`. `!=` calls an object's `__ne__`, which libraries can override. For Polars or pandas objects, `!=` returns an element-wise result rather than a bool.

#### A10. Exceptions vs warnings vs print

```python
raise KeyError(f"Append files are missing columns: {sorted(missing)}")   # stop
warnings.warn(f"{n_bad} rows have an unparseable CreatedAt (stored as null)")  # alert, continue
print("Shape:", ledger.shape)   # plain output, only under __main__
```

| Use | When | Loader example |
|---|---|---|
| `raise` | Continuing would produce **wrong results**; the caller must fix something | required columns missing |
| `warnings.warn` | Result is usable but the user should know; caller can filter or escalate | no append files; some null dates |
| `print` | Normal informational output in scripts/CLI | `__main__` block |
| `logging` | Production pipelines (levels, timestamps, files) | a suggested upgrade |

The Python docs describe warnings as for situations where it is useful to alert the user to a condition that normally doesn't warrant raising an exception and terminating the program. The default category is `UserWarning`.\[15\]\[16\] Warnings can be escalated to errors in tests: `warnings.simplefilter("error")`.\[17\]

Catching exceptions (not used in the loader, but you will need it):

```python
try:
    ledger = get_final_ledger()
except KeyError as e:
    print("Schema problem:", e)
```

#### A11. `datetime`, `timedelta` and format codes

```python
from datetime import datetime, timedelta
now = datetime.now()
yesterday = now - timedelta(days=1)
s = now.strftime("%d %b %Y %H:%M:%S")                         # datetime -> string ("f" = format)\[18\]
dt = datetime.strptime("05 Oct 2026 09:30:15", "%d %b %Y %H:%M:%S")  # string -> datetime ("p" = parse)
(now - dt).days                                               # subtraction gives a timedelta
```

**Format-code reference** (Python and Polars share these.\[19\] Polars follows the Rust *chrono* spec, which has a few extras):\[6\]\[20\]

| Code | Meaning | Example |
|---|---|---|
| `%Y` | 4-digit year | 2026 |
| `%y` | 2-digit year | 26 |
| `%m` | month, zero-padded | 10 |
| `%b` | abbreviated month name | Oct |
| `%B` | full month name | October |
| `%d` | day, zero-padded | 05 |
| `%H` | hour 00–23 | 09 |
| `%I` | hour 01–12 | 09 |
| `%p` | AM/PM | AM |
| `%M` | minute | 30 |
| `%S` | second | 15 |
| `%f` | microseconds (Python) | 123000 |
| `%.3f` / `%.f` | fractional seconds (Polars/chrono) | .123 |
| `%z` | UTC offset | +0400 |
| `%F` | = `%Y-%m-%d` | 2026-10-05 |
| `%T` | = `%H:%M:%S` | 09:30:15 |

So `BASE_DATE_FORMAT = "%d %b %Y %H:%M:%S"` matches `05 Oct 2026 09:30:15`, and `APPEND_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"` matches `2026-10-05 09:30:15`. In Python's own `strptime`, `%b` depends on the locale.

The notebooks also import `os` (file and environment operations, e.g. `os.getcwd()`, `os.listdir()`) and `numpy as np` (numeric arrays, `np.where`, `np.nan`). Neither is used yet in the visible cells.

---

### PART B: Polars concepts

#### B1. Eager vs lazy

| | Eager | Lazy |
|---|---|---|
| Object | `pl.DataFrame` | `pl.LazyFrame` (a *query plan*) |
| Read CSV | `pl.read_csv` | `pl.scan_csv` |
| When work happens | each line, immediately | only at `.collect()` |
| Optimizer | limited | full (pushdowns, etc.) |

The user guide says that in the lazy API, the query is only evaluated once it is collected. Deferring execution to the last minute can have significant performance advantages, which is why the lazy API is preferred in most cases.\[1\] The optimizations page lists:
- **Predicate pushdown**: "Applies filters as early as possible/ at scan level."\[2\]
- **Projection pushdown**: "Select only the columns that are needed at the scan level."\[2\]
- Slice pushdown, common subplan elimination, simplify expressions, type coercion, and others.\[2\]

**Why "unused columns (e.g. Narration) are never parsed":** `final.select(list(columns))` runs before `.collect()`. The optimizer sees that only six columns are needed and pushes that projection into each `scan_csv`, so `Narration` is never converted into a column. Inspect it yourself:

```python
lf = (pl.scan_csv("Ledger.csv")
        .filter(pl.col("Debit") > 0)
        .select("ClientID", "Debit"))
print(lf.explain())   # look for PROJECT 2/N COLUMNS and the SELECTION inside the scan
```

#### B2. Schema inference

- CSVs have no types, so Polars **guesses** each column's dtype from the first `infer_schema_length` rows. The current `scan_csv` default is 100. When set to `None`, "the full data will be scanned into memory (this is slow)".\[21\]
- The error `could not parse "ABC12" as dtype i64` means the first N rows of a column looked like integers but a later row didn't. Fixes, from best to worst:
  1. Declare the type explicitly: `pl.scan_csv(path, schema_overrides={"ClientID": pl.String})`
  2. Raise `infer_schema_length` (the loader uses `10_000`)
  3. `infer_schema_length=None` (slow, but scans everything)
- `lf.collect_schema()` resolves and returns the schema (column names → dtypes) **without** materializing data. `.names()` gives the column list. The loader uses this to validate columns before doing real work.

#### B3. Expressions: the heart of Polars

An **expression** is a *recipe* for a column computation. It does nothing until a context runs it.

```python
created = (
    pl.col("date_time")                 # refer to a column
    .cast(pl.String)                    # force string dtype (in case it was inferred otherwise)
    .str.strip_chars()                  # trim leading/trailing whitespace
    .str.replace("T", " ", literal=True)# ISO 'T' separator -> space (first match only)
    .str.slice(0, 19)                   # keep first 19 chars: 'YYYY-MM-DD HH:MM:SS'
    .str.to_datetime(APPEND_DATE_FORMAT, time_unit="us", strict=False)
)
```

| Piece | Meaning |
|---|---|
| `pl.col("x")` | reference column `x` |
| `pl.lit(True)` | a literal constant, broadcast to every row |
| `.alias("new")` | name the output column |
| `.cast(pl.String)` | change dtype (`pl.Int64`, `pl.Float64`, `pl.Datetime`, …) |
| `.str.…` | **namespace** of string methods (also `.dt.…` for dates, `.list.…`) |
| `strip_chars()` | trims whitespace; the Polars API docs state `str.strip` was "Deprecated since version 0.19.3: This method has been renamed to strip_chars()" (`lstrip`/`rstrip` became `strip_chars_start`/`strip_chars_end`) |
| `replace(pattern, value, literal=True)` | `literal=True` = plain text, not regex; replaces the **first** match (`replace_all` for all) |
| `slice(offset, length)` | substring |
| `to_datetime(format, time_unit="us", strict=False)` | parse to `Datetime[μs]`; failures → null |

On `time_unit`: per the docs, if it is left as `None`, it is inferred from the format (e.g. `%.3f` → ms), with "us" as the default.\[22\]\[23\] Passing `"us"` explicitly guarantees both sources produce the *same* dtype, so concatenation never meets `Datetime[ms]` vs `Datetime[us]`.

**Method chaining** (a value on each line, wrapped in parentheses) is the idiomatic Polars style. The outer `(...)` lets you break lines without backslashes.

#### B4. Contexts: where expressions run

The user guide says Polars expressions need a *context* to produce a result.\[24\] The common ones are `select`, `with_columns`, `filter` and `group_by().agg()`.\[24\]

```python
lf.select(pl.col("a"), (pl.col("b") * 2).alias("b2"))   # ONLY these columns come out
lf.with_columns(_is_base=pl.lit(True))                    # all existing columns + new/overwritten
lf.filter(pl.col("Debit") > 0)                            # keep rows where expression is True
lf.drop("_is_base")                                       # remove columns
```

- `with_columns(_is_base=pl.lit(True))` is the **keyword form** and is the same as `with_columns(pl.lit(True).alias("_is_base"))`. The guide calls these "named expressions".\[25\]
- Difference noted in the docs: `with_columns` keeps the original columns and adds new ones. `select` returns only what you list.\[24\]

#### B5. `pl.concat` strategies

From the official API (`how` is keyword-only, default `'vertical'`):\[5\]\[26\]

| `how` | Rule | When to use | Ledger example |
|---|---|---|---|
| `vertical` | same column names **and** dtypes; stacks rows | identical, trusted exports | 12 monthly files from the same system |
| `vertical_relaxed` | same names; dtypes coerced to a common supertype | same layout, inference differs | `Debit` read as i64 in one file, f64 in another |
| `diagonal` | union of columns; missing ones filled with null | files gained or lost columns | base has `Narration`, appends don't |
| `diagonal_relaxed` | diagonal **+** supertype coercion | heterogeneous, drifting sources | **your loader** |
| `horizontal` | side by side (more columns); per the Polars 2.0 upgrade guide it "now always requires equal heights" (`horizontal_extend` keeps the old null-padding) | aligned row sets | adding a computed block |
| `align` | joins on common columns | rarely needed | — |

```python
a = pl.DataFrame({"x": [1], "y": [3]})
b = pl.DataFrame({"x": [2.5], "z": [4]})
pl.concat([a, b], how="diagonal_relaxed")
# x: f64 (1.0, 2.5), y: (3, null), z: (null, 4)
```

#### B6. Boolean logic and broadcast aggregations

```python
base_max = pl.col("CreatedAt").filter(pl.col("_is_base")).max()
final = final.filter(pl.col("_is_base") | (pl.col("CreatedAt") > base_max))
```

- In Polars and pandas you combine conditions with `|` (or), `&` (and) and `~` (not). Python's `and`/`or`/`not` don't work on columns, because they try to turn a whole column into a single `True`/`False`.
- **Parentheses are required.** The Python reference documents that comparisons rank **lower** than the bitwise operators `&` and `|`.\[27\] So `pl.col("a") | pl.col("b") > 5` is parsed as `(pl.col("a") | pl.col("b")) > 5`, which is wrong. Always wrap each comparison: `(cond1) | (cond2)`.
- **Aggregation inside an expression**: `pl.col("CreatedAt").filter(pl.col("_is_base")).max()` computes **one value** (the latest base timestamp). The user guide notes that "broadcasting can also occur within expressions" when a subexpression evaluates to a single value.\[24\] So comparing each row's `CreatedAt` to it works row by row. The base file is read once, in the same pass.
- **Null logic (Kleene)**: `True | null` = `True`, so base rows are kept even with null dates. `False | null` = `null`, which `filter` treats as "drop".

#### B7. Results and conversion

```python
df = final.collect()              # LazyFrame -> DataFrame (work happens here)
df["CreatedAt"]                   # Series (one column)
df["CreatedAt"].null_count()      # int
df["CreatedAt"].max()             # scalar
df.shape                          # (rows, cols) tuple
df.head()                         # first 5 rows
df.columns                        # list of names
df.to_pandas()                    # pandas DataFrame
```

According to the Polars docs, `to_pandas` "requires that both pandas and pyarrow are installed". By default it copies data into NumPy-backed columns, and nulls in numeric columns become NaN. `use_pyarrow_extension_array=True` keeps Arrow-backed columns and preserves nulls.\[28\]

#### B8. pandas ↔ Polars equivalents

| Task | pandas | Polars |
|---|---|---|
| Read CSV eagerly | `pd.read_csv(p)` | `pl.read_csv(p)` |
| Read lazily | — | `pl.scan_csv(p)` … `.collect()` |
| Select columns | `df[["a","b"]]` | `df.select("a","b")` |
| Filter rows | `df[df["a"] > 5]` | `df.filter(pl.col("a") > 5)` |
| Combine conditions | `df[(df.a>5) & (df.b<3)]` | `df.filter((pl.col("a")>5) & (pl.col("b")<3))` |
| Add column | `df["c"] = df.a*2` / `df.assign(c=...)` | `df.with_columns(c=pl.col("a")*2)` |
| Rename | `df.rename(columns=mapping)` | `df.rename(mapping)` |
| Drop | `df.drop(columns=["x"])` | `df.drop("x")` |
| Stack frames | `pd.concat([a,b], ignore_index=True)` | `pl.concat([a,b])` (`how=` for drift) |
| Parse dates | `pd.to_datetime(s, format=f, errors="coerce")` | `.str.to_datetime(f, strict=False)` |
| Trim strings | `s.str.strip()` | `.str.strip_chars()` |
| Substring | `s.str[:19]` | `.str.slice(0, 19)` |
| Cast | `s.astype(str)` | `.cast(pl.String)` |
| Count missing | `s.isna().sum()` | `s.null_count()` |
| Group + agg | `df.groupby("k")["v"].sum()` | `df.group_by("k").agg(pl.col("v").sum())` |
| Row index | always present | none; add with `with_row_index()` |
| Missing values | `NaN`/`NaT`/`None` | `null` (ints stay ints) |

The Polars migration guide says Polars uses the Arrow memory format, supports lazy evaluation (pandas is eager only), and is strict about data types. pandas converts types loosely (e.g. an integer column with missing values becomes float).\[29\]

---

### PART C: Design patterns, mapped to data engineering

| Pattern in the loader | Where | Data-engineering name | Why it's good |
|---|---|---|---|
| Config block at top | `BASE_LEDGER_PATH`, formats, `INFER_ROWS` | configuration / parameterization | change behaviour without touching logic; next step: env vars or YAML |
| Loaders separate from entry point | `scan_*` vs `get_final_ledger` | separation of concerns | each piece is testable and reusable |
| Rename map | `APPEND_COLUMN_MAP` | **schema mapping / conformance** (staging layer) | heterogeneous sources → one standard schema |
| Missing-column check before work | `missing = set(...) - set(...)` | **data contract / schema validation** | fail fast with a clear message |
| `diagonal_relaxed` | `pl.concat` | **schema-drift tolerance** | survives column-order and dtype differences |
| Normalize → parse → count nulls → warn | `created` expr + `null_count` | **data-quality check** | bad rows are visible, not silent |
| Helper column `_is_base`, dropped later | `with_columns` / `drop` | **lineage / source tagging** | lets you treat sources differently in one pass |
| `only_new_appends` | filter vs `base_max` | **incremental load / high-water mark / dedup guard** | avoids double-counting overlapping exports |
| One `.collect()` at the end | `get_final_ledger` | push compute to the engine | same idea as letting a warehouse optimize SQL |
| `as_pandas` flag | return line | **adapter / interface boundary** | new engine without breaking old pandas code |

**Link to dbt:** dbt's documentation describes incremental models as "built as tables in your data warehouse. The first time a model is run, the table is built by transforming *all* rows of source data. On subsequent runs, dbt transforms *only* the rows in your source data that you tell dbt to filter for." Its canonical filter, `where event_time >= (select coalesce(max(event_time),'1900-01-01') from {{ this }})`, is the same high-water-mark logic as your `CreatedAt > base_max`.\[30\] If you can explain your loader in these terms in an interview, you are speaking analytics engineering.

---

### PART D: Fixing `ModuleNotFoundError: No module named 'ledger_loader'`

**Root cause:** both notebooks call `from ledger_loader import ...`. Python searches `sys.path`, whose first entry for a kernel is its working directory (typically the notebook's folder). `ledger_loader.py` is in a different folder, so the lookup fails. Installing packages won't help, because this is your own file.

**Fixes, from simplest to most professional:**

| # | Fix | Code / action | Pros | Cons |
|---|---|---|---|---|
| 1 | Same folder | Copy/move `ledger_loader.py` next to both `.ipynb` files | zero code | duplicate copies drift apart |
| 2 | `sys.path.insert` | see below | explicit, one place | hard-coded path in every notebook |
| 3 | `os.chdir(folder)` | `os.chdir(r"C:\path\to\loader_folder")` before import | quick | changes all relative paths in the notebook; fragile |
| 4 | `PYTHONPATH` env var | Windows: System Properties → Environment Variables → add `PYTHONPATH=C:\path\to\loader_folder`; restart Jupyter | no code changes | invisible to others; machine-specific |
| 5 | Installable package | folder with `pyproject.toml` + `pip install -e .` | works from anywhere in that env; the professional route | small upfront setup |

**Recommended cell for each notebook (fix #2 + autoreload):**

```python
%load_ext autoreload
%autoreload 2

import sys
from pathlib import Path

LOADER_DIR = Path(r"C:\Users\Administrator\<folder-containing-ledger_loader>")
if str(LOADER_DIR) not in sys.path:
    sys.path.insert(0, str(LOADER_DIR))   # insert(0) = search here FIRST

from ledger_loader import get_final_ledger
ledger = get_final_ledger()                      # Polars
# ledger_pd = get_final_ledger(as_pandas=True)   # pandas, for existing pandas code
```

- `insert(0, …)` puts your folder ahead of everything else; `append` puts it last. Use `insert` if a same-named module might exist elsewhere.
- **Autoreload**: per the IPython docs, `%autoreload 2` reloads all modules (except excluded ones) every time before executing typed code.\[31\] You can then edit `ledger_loader.py` and re-run a cell without restarting the kernel. It can't reload C extensions, and it is not 100% reliable after big structural changes.\[32\]\[33\] Restart the kernel if behaviour looks stale. IPython 8.0 added `%autoreload 3`, which per the IPython 8.x what's-new page will "autoload all new funcs/classes/enums/globals from the module when they are added" (aliased `%autoreload complete` since 8.11).

**Fix #5 skeleton (editable install):**

```
ledger_tools/
├── pyproject.toml
└── ledger_loader.py
```
```toml
[project]
name = "ledger-tools"
version = "0.1.0"
dependencies = ["polars>=1.0", "pyarrow"]
```
Then, in the kernel's environment: `python -m pip install -e C:\path\to\ledger_tools`. "Editable" means imports point at your source folder, so edits take effect without reinstalling (you still need autoreload or a kernel restart). Re-install if you change `pyproject.toml`.\[34\]\[35\]

**Environment check: the kernel must have polars and pyarrow:**

```python
import sys; print(sys.executable)     # the Python that runs THIS notebook
%pip install polars pyarrow           # %pip installs into the running kernel's environment
import polars as pl; print(pl.__version__)
```

Use `%pip`, not `!pip`. `!pip` runs whatever `pip` is first on the system PATH, which may belong to a different Python. If your environment doesn't appear in Jupyter's kernel list, register it from inside the activated environment: `python -m pip install ipykernel` then `python -m ipykernel install --user --name ledger --display-name "Python (ledger)"`.\[36\]\[37\]\[38\]\[39\]

---

### PART E: Line-by-line walkthrough of `ledger_loader.py`

**Header**
- `"""ledger_loader.py (Polars version) ..."""`: module docstring, which says what the module builds, its requirements and how to use it. Writing usage examples in the docstring is a professional habit.

**Imports**
- `import warnings`: standard-library module for non-fatal alerts.
- `from pathlib import Path`: object-oriented filesystem paths.
- (blank line): separates stdlib from third-party (PEP 8 grouping).
- `import polars as pl`: third-party; `pl` is the community-standard alias.

**Configuration**
- `BASE_LEDGER_PATH = Path(r"...Ledger.csv")`: raw string, so backslashes stay literal. Wrapped in `Path` for path methods.
- `APPEND_FOLDER = Path(r"...zynix_led_append")`: the folder of incremental exports.
- `BASE_DATE_FORMAT = "%d %b %Y %H:%M:%S"`: matches `05 Oct 2026 09:30:15`.
- `APPEND_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"`: matches the first 19 characters of ISO-like strings.
- `INFER_ROWS = 10_000`: rows sampled for dtype guessing (PEP 515 underscore).
- `APPEND_COLUMN_MAP = {...}`: raw snake_case names → standard PascalCase names. It is both the rename spec **and** the list of required columns.
- `FINAL_COLUMNS = (...)`: a tuple, so it is an immutable default for `columns`.

**`scan_base_ledger(path=BASE_LEDGER_PATH) -> pl.LazyFrame`**
- `pl.scan_csv(path, infer_schema_length=INFER_ROWS)`: lazy read; nothing is loaded yet.
- `.with_columns(pl.col("CreatedAt").str.strip_chars().str.to_datetime(BASE_DATE_FORMAT, time_unit="us", strict=False))`: overwrites `CreatedAt` (same name, no alias needed) with a parsed datetime. It trims stray spaces first, because one leading space would make every parse fail. `strict=False` turns failures into null instead of crashing.

**`scan_append_files(folder=APPEND_FOLDER) -> pl.LazyFrame | None`**
- `files = sorted(Path(folder).glob("*.csv"))`: all CSVs, deterministic order.
- `if not files: warnings.warn(...); return None`: a guard clause. Having no appends is legitimate, so it warns rather than raising.
- `lf = pl.concat([pl.scan_csv(f, ...) for f in files], how="diagonal_relaxed")`: one lazy scan per file, combined. Separate scans let each file infer its own schema, and `diagonal_relaxed` reconciles column order and dtype differences.
- `missing = set(APPEND_COLUMN_MAP) - set(lf.collect_schema().names())`: required raw names minus the names actually present. `collect_schema()` resolves only the schema (from headers plus the inference sample), not the data.
- `if missing: raise KeyError(...)`: fail fast with the sorted list of missing columns.
- `created = (...)`: the defensive date expression from B3. `.cast(pl.String)` comes first because a column could be inferred as something other than string. Note that `.str.slice(0, 19)` **floors** fractional seconds and **drops** the UTC offset (it keeps wall-clock time).
- `return lf.select(... for src, dst in APPEND_COLUMN_MAP.items())`: in one projection, every raw column is renamed to its standard name. `date_time` is replaced by the parsed `created`. Any column **not** in the map is dropped.

**`get_final_ledger(...)`**
- `base = scan_base_ledger(base_path).with_columns(_is_base=pl.lit(True))`: tag base rows. The leading underscore signals "internal/temporary".
- `appends = scan_append_files(append_folder)`: a LazyFrame or `None`.
- `frames = [base]` / `if appends is not None: frames.append(appends.with_columns(_is_base=pl.lit(False)))`: build the list conditionally.
- `final = pl.concat(frames, how="diagonal_relaxed")`: base and appends are unioned. Base-only columns (e.g. `Narration`) are null for append rows, and dtypes are unified.
- `if only_new_appends:`: optional overlap guard. `base_max` is the latest base timestamp (a broadcast scalar), and the filter keeps all base rows plus strictly newer appends.
- `final = final.drop("_is_base")`: remove the helper column.
- `if columns is not None: final = final.select(list(columns))`: final projection, which enables projection pushdown.
- `df = final.collect()`: the **only** line that actually reads files.
- `if "CreatedAt" in df.columns:`: guard in case a caller excluded the column.
- `n_bad = df["CreatedAt"].null_count(); if n_bad: warnings.warn(...)`: data-quality report.
- `return df.to_pandas() if as_pandas else df`: ternary return; pandas only when asked.

**Main guard**
- `if __name__ == "__main__":`: a smoke test when run as a script: latest timestamp, shape, first rows.

---

### PART F: Write it yourself

#### F1. Module skeleton (config + functions + main guard)

```python
"""<module_name>.py — one-line purpose.

Usage:
    from <module_name> import main_function
"""
import warnings
from pathlib import Path

import polars as pl

# ---- Configuration ----
DATA_DIR = Path(r"C:\data\input")
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
REQUIRED = ("id", "created_at", "amount")


# ---- Helpers ----
def _validate(lf: pl.LazyFrame, required=REQUIRED) -> None:
    missing = set(required) - set(lf.collect_schema().names())
    if missing:
        raise KeyError(f"Missing columns: {sorted(missing)}")


# ---- Entry point ----
def load(data_dir=DATA_DIR, as_pandas=False):
    """Load, standardize and return the data."""
    ...
    return df.to_pandas() if as_pandas else df


if __name__ == "__main__":
    print(load().head())
```

#### F2. Generic multi-CSV loader

```python
def scan_folder(folder, pattern="*.csv", rename=None, infer=10_000) -> pl.LazyFrame | None:
    files = sorted(Path(folder).glob(pattern))
    if not files:
        warnings.warn(f"No files matching {pattern} in {folder}")
        return None
    lf = pl.concat([pl.scan_csv(f, infer_schema_length=infer) for f in files],
                   how="diagonal_relaxed")
    if rename:
        _validate(lf, required=rename.keys())
        lf = lf.select(pl.col(src).alias(dst) for src, dst in rename.items())
    return lf
```

#### F3. Defensive date-parsing pattern

```python
def parse_dt(col: str, fmt: str, n_chars: int | None = None) -> pl.Expr:
    e = pl.col(col).cast(pl.String).str.strip_chars()
    if n_chars:
        e = e.str.slice(0, n_chars)
    return e.str.to_datetime(fmt, time_unit="us", strict=False)

df = lf.with_columns(parsed=parse_dt("raw_ts", "%Y-%m-%d %H:%M:%S", 19)).collect()
bad = df.filter(pl.col("parsed").is_null() & pl.col("raw_ts").is_not_null())
if bad.height:
    warnings.warn(f"{bad.height} unparseable timestamps, e.g. {bad['raw_ts'].head(3).to_list()}")
```
Unlike the loader, this version separates "was empty" from "failed to parse" and shows examples.

#### F4. Graded exercises (write each from a blank file and check it against the original only afterwards)

**Beginner**
1. Write a function `list_csvs(folder)` that returns sorted CSV paths and prints a warning if none exist. *Hint:* `Path.glob`, `sorted`, `if not`.
2. Given `m = {"a": "A", "b": "B"}` and `cols = ["a", "x"]`, compute which keys of `m` are missing from `cols`. *Hint:* set difference.
3. Parse `"05 Oct 2026 09:30:15"` with `datetime.strptime`, add 90 minutes, print it as `2026-10-05 11:00`. *Hint:* `timedelta(minutes=90)`, `%Y-%m-%d %H:%M`.
4. Rewrite `[x.upper() for x in names if x]` as a plain `for` loop, then back again.

**Intermediate**
5. Build a 5-row Polars DataFrame with messy timestamps (`" 2026-10-05T09:30:15.5+04:00"`, `"bad"`, `None`, ...). Write the expression chain that parses them, and count the nulls. *Hint:* B3.
6. Make two DataFrames with different columns and dtypes. Try each `how=` in `pl.concat` and write down which ones fail and why.
7. Write a filter keeping rows where `Debit > 0` **or** `LedgerType == "FEE"`, first without parentheses, then with them. Explain the error or wrong result.
8. Convert one of your existing pandas notebook cells into Polars using the B8 table.

**Advanced**
9. Rebuild `get_final_ledger` from memory, including `only_new_appends`. Then call `.explain()` on the LazyFrame before collecting and find where the projection was pushed into the scans.
10. Fix the silent-drop issue: make `only_new_appends=True` also report how many appended rows had null `CreatedAt`. *Hint:* compute the count in a separate lazy query, or keep null-dated rows in the filter: `| pl.col("CreatedAt").is_null()`.
11. Add deduplication on `SLNo.` for append rows (`.unique(subset=[...], keep="last")`). Explain why it must happen *before* `select(FINAL_COLUMNS)`.
12. Write `test_ledger_loader.py` with pytest. Use the `tmp_path` fixture to write two tiny CSVs, call `get_final_ledger(base_path=..., append_folder=...)`, and `assert` the shape, the dtypes, and that a bad date produces a warning (`pytest.warns(UserWarning)`).

#### F5. Self-check quiz

1. Why does `import ledger_loader` work in a terminal from the loader's folder but fail in the notebook?
2. What does `scan_csv` return, and when is the file actually read?
3. Difference between `select` and `with_columns`?
4. What does `strict=False` do in `to_datetime`, and what must you do afterwards?
5. Why must `(a > 1) | (b < 2)` have parentheses?
6. When would you use `vertical_relaxed` instead of `diagonal_relaxed`?
7. Why is `FINAL_COLUMNS` a tuple?
8. What does `-> pl.LazyFrame | None` tell a caller?
9. Why `warnings.warn` for "no files" but `raise` for "missing columns"?
10. What does `%autoreload 2` solve?

**Answers:** (1) `sys.path[0]` is the current directory; the kernel's current directory is the notebook folder, not the loader's. (2) A `LazyFrame`; the file is read at `.collect()`. (3) `select` returns only the listed expressions; `with_columns` keeps all columns and adds or overwrites. (4) Failures become null; count the nulls and warn or raise. (5) In Python, `|` binds tighter than `>`/`<`, so without parentheses the comparison applies to the wrong operand. (6) When all files have the same column names but dtypes differ; it is stricter, so a renamed column raises instead of silently becoming a new column. (7) It is an immutable, safe default argument. (8) It may return `None`, so check `is not None`. (9) No appends is a valid state, while missing columns would produce wrong data. (10) Picking up edits to imported `.py` files without restarting the kernel.

---

### PART G: Common pitfalls and debugging

| Symptom | Cause | Fix |
|---|---|---|
| `SyntaxError: (unicode error) 'unicodeescape'` | `"C:\Users..."` without `r` | `r"C:\Users..."` or forward slashes |
| All `CreatedAt` null + big warning | format mismatch (e.g. file switched to `05/10/2026`) or locale/month names | print 5 raw values (`df["CreatedAt"].head()` before parsing) and compare to the format character by character |
| Some nulls | mixed formats, blanks, non-padded `2026-10-5 9:30:15` (slice(0,19) cuts it wrongly) | inspect `filter(parsed.is_null() & raw.is_not_null())` |
| `could not parse "ABC12" as dtype i64` | inference sampled only numbers | `schema_overrides={"ClientID": pl.String}` |
| Filter returns wrong rows or a dtype error | missing parentheses around comparisons | `(cond1) & (cond2)` |
| You see `<LazyFrame ...>` instead of data | forgot `.collect()` | collect once at the end |
| `AttributeError: 'DataFrame' object has no attribute 'with_columns'` / `'assign'` | mixing pandas and Polars objects | check `type(df)`; convert at one boundary with `to_pandas()` / `pl.from_pandas()` |
| `ImportError ... pyarrow` on `as_pandas=True` | pyarrow missing in kernel env\[40\] | `%pip install pyarrow` |
| Installed with pip, still `ModuleNotFoundError` | terminal pip ≠ kernel Python | compare `sys.executable`; use `%pip`\[39\]\[41\] |
| Edits to `.py` not reflected | module cached on first import | `%autoreload 2` or restart kernel |
| Appended rows missing with `only_new_appends=True` | null dates silently dropped (Key Finding 5) | add `| pl.col("CreatedAt").is_null()` or count them separately |
| New half-null column appears | source renamed a column; `diagonal` unions names | validate the base schema too; consider `vertical_relaxed` for trusted sources |

**Reading a traceback:** read from the **bottom up**. The last line is the exception type and message. The last frame pointing to *your* file is usually where to look. Polars errors often suggest fixes; the Polars 2.0 guide shows a parse error ending "You might want to try: increasing `infer_schema_length` (e.g. `infer_schema_length=10000`), specifying correct dtype with the `schema_overrides` argument, setting `ignore_errors` to `True`".

---

## Recommendations

### 1. Habits that build logic and syntax independently
- **Pseudocode first.** Before writing, list the steps in plain English (e.g. "find files → scan each → check columns → rename → parse dates → combine → collect → check nulls"). The loader is exactly this list translated.
- **Rewrite without looking.** After studying a piece of code, close it and rewrite it in a blank file, then diff. Do this for `ledger_loader.py` three times over two weeks.
- **Explore in the REPL** with `type(x)`, `dir(x)`, `help(pl.concat)`, `pl.col("a").str.<Tab>`. Polars docstrings include runnable examples.
- **Read the signature, then the examples** in the official API pages (`docs.pola.rs/api/python/stable/...`). Note the `*` keyword-only marker and the defaults.
- **Test tiny cases.** Build a 3-row DataFrame to test any expression before running it on the full ledger. Turn the useful ones into `assert` statements, then into pytest tests.
- **Use `.explain()`** on lazy queries to see what Polars actually does.
- **Keep a personal cheat sheet** (your own words plus a minimal example) for every new method you meet.

### 2. 8-week learning plan (about 5–7 hrs/week)

| Week | Focus | Concrete deliverable |
|---|---|---|
| 1 | Python core: official tutorial ch. 3–5 (types, control flow, data structures) | Exercises 1–4; cheat sheet of dict/set/list/tuple |
| 2 | Functions, modules, `sys.path`, exceptions (tutorial ch. 4, 6, 8) | Fix both notebooks; package the loader with `pip install -e` |
| 3 | Polars: user guide "Getting started", "Expressions and contexts", "Lazy API" | Exercises 5–7 |
| 4 | Polars: strings, dates, `concat`, `join`, `group_by` | Port one pandas notebook to Polars (Ex. 8) |
| 5 | Rebuild the loader from memory; `.explain()` | Ex. 9–11 |
| 6 | Testing + git: pytest basics, a GitHub repo for the loader | Ex. 12; first commit history |
| 7 | SQL depth: window functions, CTEs; do the same ledger logic in DuckDB SQL | SQL version of "latest balance per client" |
| 8 | dbt fundamentals: staging → intermediate → marts; an incremental model | dbt project mirroring your loader (staging = rename map, incremental = high-water mark) |

### 3. Resources (prioritized)
- **Official:** Python Tutorial (docs.python.org/3/tutorial); Python Library Reference pages for `pathlib`, `datetime`, `warnings`; PEP 8; Polars User Guide (docs.pola.rs) including "Coming from pandas"; pandas "10 minutes to pandas"; IPython docs (autoreload, kernel install); Python Packaging User Guide (pyproject.toml).
- **Books:** *Python Crash Course* (Matthes) or *Automate the Boring Stuff* (Sweigart) for foundations; *Effective Pandas* (Harrison); *Fluent Python* (Ramalho) once you're comfortable; *Fundamentals of Data Engineering* (Reis & Housley); *The Data Warehouse Toolkit* (Kimball) for modeling.
- **Practice:** Exercism Python track (mentored feedback); Advent of Code for logic; DataLemur / LeetCode SQL for interview SQL; dbt Learn's free fundamentals course.

### 4. Translating this into analytics-engineering roles (DIFC fintech)
- **Portfolio project:** publish a sanitized version of this pipeline (synthetic ledger data, never real client data) on GitHub with: the loader packaged, pytest tests, a README explaining the incremental-load and data-quality design, and a dbt + DuckDB version with `unique`/`not_null` tests on `SLNo.`/`ClientID`.
- **Interview framing:** describe the loader as "ingestion with schema conformance, schema-drift tolerance, high-water-mark incremental loading and data-quality checks". Then explain the trade-off of `diagonal_relaxed` and the null-date edge case you found. Spotting edge cases like that is what separates engineers from script writers.
- **Next skills:** SQL window functions, dimensional modeling (facts and dimensions, e.g. `fct_ledger_entries`, `dim_client`), git branching and pull requests, CI running pytest/dbt tests, and `logging` instead of `print`.

### 5. Suggested upgrades to the loader itself (good practice targets)
1. Validate base `Ledger.csv` columns too, not only the appends.
2. Declare known dtypes with `schema_overrides` (e.g. `ClientID` as `pl.String`, money columns as `pl.Float64` or `pl.Decimal`) instead of relying on inference.
3. Report null-date counts **per source** and **before** the `only_new_appends` filter.
4. Deduplicate on `SLNo.` for overlapping append files.
5. Replace `warnings.warn` with `logging` once this runs on a schedule.

---

## Caveats
- `cohort_analysis.ipynb` could not be read; paste it to extend these notes.
- Polars' API changes between versions. This guide uses current names (`strip_chars`, `collect_schema`, `with_columns`, `group_by`). Older blog posts use `strip`, `groupby` and others. The Polars user guide's "Version 2.0" upgrade page sets `scan_csv`'s `infer_schema_files` default to 10, so "Multi-file CSV scans now only inspect the first 10 files (instead of all of them) to infer the schema by default." Your loader scans each file separately and sets `infer_schema_length` explicitly, so it is largely insulated, but check `pl.__version__` before upgrading: the same guide says "The Lazy API defaults to the streaming engine", which "does not guarantee row order" for operations like `group_by` and joins (restore with `lf.collect(engine="in-memory")`).
- Polars parses dates with the Rust *chrono* format spec, which mostly but not completely matches Python's `strptime`. Test any new format on sample strings.
- The kernel's working directory depends on the front-end. Classic Jupyter and JupyterLab use the notebook's folder, but VS Code may use the workspace root depending on its settings. Always confirm with `os.getcwd()`.
- Book and course recommendations reflect widely used community resources rather than an official endorsement. Pick one per stage and finish it rather than sampling many.

## Sources

1. [Lazy API - Polars user guide](https://docs.pola.rs/user-guide/concepts/lazy-api/)
2. [Optimizations - Polars user guide](https://docs.pola.rs/user-guide/lazy/optimizations/)
3. [polars.concat — Polars documentation](https://pola-rs.github.io/polars/py-polars/html/reference/api/polars.concat.html)
4. [concat - Polars R Package](https://pola-rs.github.io/r-polars/man/pl__concat.html)
5. [Concatenating Frames · Data Wrangling with Python Polars · Dataslope](https://dataslope.com/courses/data-wrangling-python-polars/concatenating-frames)
6. [polars.Expr.str.to\_datetime — Polars documentation](https://docs.pola.rs/api/python/stable/reference/expressions/api/polars.Expr.str.to_datetime.html)
7. [str\_to\_datetime - Polars R Package](https://pola-rs.github.io/r-polars/man/expr_str_to_datetime.html)
8. [\_\_main\_\_ — Top-level code environment — Python 3.15.2 documentation](https://docs.python.org/3/library/__main__.html)
9. [What Does if \_\_name\_\_ == "\_\_main\_\_" Do in Python?](https://realpython.com/if-name-main-python/)
10. [\_\_main\_\_ — Top-level code environment — Python 3.10.20 documentation](https://docs.python.org/3.10/library/__main__.html)
11. [6\. Modules — Python 3.15.1 documentation](https://docs.python.org/3/tutorial/modules.html)
12. [PEP 515](https://peps.python.org/pep-0515/)
13. [What is PEP 604?](https://pydevtools.com/handbook/explanation/what-is-pep-604/)
14. [What’s New In Python 3.10 — Python 3.15.1 documentation](https://docs.python.org/3/whatsnew/3.10.html)
15. [27.5. warnings — Warning control — Python v2.6.9 documentation](https://docs.python.org/2.6/library/warnings.html)
16. [warnings — Warning control — Python 3.9.2 documentation](https://www.cs.unb.ca/~bremner/teaching/cs2613/books/python3-doc/library/warnings.html)
17. [Warnings in Python - GeeksforGeeks](https://www.geeksforgeeks.org/python/warnings-in-python/)
18. [Working With Datetime Objects in Python: The Complete Guide](https://inventivehq.com/blog/working-with-datetime-objects-in-python)
19. [Python strptime/strftime Format Finder](https://www.pythonmorsels.com/strptime/)
20. [datetime — Basic date and time types — Python 3.15.2 documentation](https://docs.python.org/3/library/datetime.html)
21. [polars.scan\_csv — Polars documentation](https://docs.pola.rs/api/python/stable/reference/api/polars.scan_csv.html)
22. [polars.Series.str.to\_datetime — Polars documentation](https://docs.pola.rs/api/python/stable/reference/series/api/polars.Series.str.to_datetime.html)
23. [polars.Expr.str.strptime — Polars documentation](https://docs.pola.rs/py-polars/html/reference/expressions/api/polars.Expr.str.strptime.html)
24. [Expressions and contexts - Polars user guide](https://docs.pola.rs/user-guide/concepts/expressions-and-contexts/)
25. [Getting started - Polars user guide](https://docs.pola.rs/user-guide/getting-started/)
26. [polars.concat — Polars documentation](https://docs.pola.rs/api/python/stable/reference/api/polars.concat.html)
27. [6\. Expressions — Python 3.15.2 documentation](https://docs.python.org/3/reference/expressions.html)
28. [polars.DataFrame.to\_pandas — Polars documentation](https://docs.pola.rs/py-polars/html/reference/dataframe/api/polars.DataFrame.to_pandas.html)
29. [Coming from Pandas - Polars user guide](https://docs.pola.rs/user-guide/migration/pandas/)
30. <https://docs.getdbt.com/docs/build/incremental-models>
31. [ipython/IPython/extensions/autoreload.py at main · ipython/ipython · GitHub](https://github.com/ipython/ipython/blob/main/IPython/extensions/autoreload.py)
32. [Automatically Reload Modules with %autoreload](https://switowski.com/blog/ipython-autoreload/)
33. [autoreload — IPython 9.17.1 documentation](https://ipython.readthedocs.io/en/stable/config/extensions/autoreload.html)
34. [A Practical Guide To Setuptools And Pyproject.toml](https://xebia.com/blog/a-practical-guide-to-setuptools-and-pyproject-toml/)
35. [How to Manage Python Projects With pyproject.toml](https://realpython.com/python-pyproject-toml/)
36. [How to Set Up Jupyter Notebook (And Why Your Environment Is Missing From the Kernel List) - DEV Community](https://dev.to/michaelnocito/how-to-set-up-jupyter-notebook-and-why-your-environment-is-missing-from-the-kernel-list-503l)
37. [ipykernel install per env](https://theneuralbase.com/jupyter-for-ml/learn/beginner/ipykernel-install-per-env/)
38. [Python Jupyter: How to Resolve "ModuleNotFoundError: No module named 'ipykernel'"](https://tutorialreference.com/python/examples/faq/python-jupyter-error-modulenotfounderror-no-module-named-ipykernel)
39. [Fix: Jupyter Notebook Not Working — Kernel Dead, Module Not Found, and Widget Errors - FixDevs](https://fixdevs.com/blog/jupyter-not-working/)
40. [Unable to convert dataframe to Pandas due to import error with pyarrow · Issue #2392 · pola-rs/polars · GitHub](https://github.com/pola-rs/polars/issues/2392)
41. [community.databricks.com](https://community.databricks.com/t5/get-started-discussions/cannot-import-editable-installed-module-in-notebook/td-p/118759)
