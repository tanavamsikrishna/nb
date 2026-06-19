"""
# NB Framework Example Notebook

This notebook demonstrates the capabilities of the `nb` execution and display framework, including:

```json
{"key":"value"}
```

```py
def func():
    print("Hello")
```

## Ordered list
1. Markdown rendering
    1. One
    2. Two
2. Collapsible JSON tree viewer
3. `@nb_cache` caching decorator
4. Auto-detected displays for Polars and Plotly

## Unordered list
- An unordered list item
- An unordered list item 2

"""

# %% Imports
import datetime
import time
import warnings
from datetime import date

import plotly.express as px
import polars as pl

from nb import display, nb_cache

# %% Introduction
display("# Welcome to the `nb` runner!", as_="md")
display("<p style='color: #2563eb;'>This HTML text is styled directly.</p>", as_="html")

for _ in range(2):
    time.sleep(1)
    display("show something")

display("## Sample numpy", as_="md")
# Generate mock sample data
df = pl.DataFrame(
    {
        "id": [1, 2, 3, 4, 5],
        "name": ["Alice", "Bob", "Charlie", "David", "Eve"],
        "age": [25, 30, 35, 40, 45],
        "joined_date": [
            date(2025, 1, 15),
            date(2025, 3, 22),
            date(2025, 5, 10),
            date(2026, 2, 18),
            date(2026, 6, 1),
        ],
        "is_active": [True, False, True, True, False],
    }
)
display(pl.concat([df] * 10))

# %% Date / time types


warnings.warn("About to call an non-existent function")

displayx("## Date / time types", as_="md")
# Exercises every temporal type the table view formats:
#   event_date   -> Date            (date-only)
#   local_ts     -> Datetime        (naive: rendered verbatim, no zone)
#   utc_ts       -> Datetime("UTC") (tz-aware: shown in your local zone,
#                                    header labels the zone, tooltip shows UTC)
#   time_of_day  -> Time            (clock time, no zone)
events = pl.DataFrame(
    {
        "event": ["login", "purchase", "logout", "refund"],
        "event_date": [
            date(2026, 6, 15),
            date(2026, 6, 16),
            date(2026, 6, 16),
            date(2026, 6, 18),
        ],
        # Sub-second detail (microseconds) is dropped from the cell display but
        # surfaced on hover, so a few rows carry fractional seconds.
        "local_ts": [
            datetime.datetime(2026, 6, 15, 9, 30, 0, 123000),
            datetime.datetime(2026, 6, 16, 14, 5, 12),
            datetime.datetime(2026, 6, 16, 18, 45, 30, 500000),
            datetime.datetime(2026, 6, 18, 8, 0, 0),
        ],
        "utc_ts": [
            datetime.datetime(2026, 6, 15, 16, 30, 0, 250000, tzinfo=datetime.timezone.utc),
            datetime.datetime(2026, 6, 16, 21, 5, 12, tzinfo=datetime.timezone.utc),
            datetime.datetime(2026, 6, 17, 1, 45, 30, tzinfo=datetime.timezone.utc),
            datetime.datetime(2026, 6, 18, 15, 0, 0, tzinfo=datetime.timezone.utc),
        ],
        "time_of_day": [
            datetime.time(9, 30, 0, 123000),
            datetime.time(14, 5, 12),
            datetime.time(18, 45, 30, 750000),
            datetime.time(8, 0, 0),
        ],
    }
)
display(events)

# %% Empty cell test
time.sleep(2)

# %% Collapsible Object Wrapper
time.sleep(1)
my_data = {
    "project": "nb",
    "version": "0.1.0",
    "features": ["caching", "streaming", "ipc", "Svelte UI"],
    "nested": {"status": "active", "port": 7777, "socket": ".nb.sock"},
}
display(my_data)
time.sleep(1)
display(f"**Hello at {datetime.datetime.now()}**", as_="md")

# %% Caching with @nb_cache

WINDOW = 3


@nb_cache(keys=["WINDOW"])
def expensive_computation(x):
    display(f"Calculating for x={x} (this should only run on cache miss)...", as_="md")
    time.sleep(1)  # simulate slow task
    return x * WINDOW


res1 = expensive_computation(3)
display(f"Result 1: {res1}")

# %% Verify Caching Hit
# This call should hit the cache, replay the md display record instantly, and return 30 without sleeping
res2 = expensive_computation(10)
display(f"Result 2: {res2}")


# %% Plotly Display

df = pl.DataFrame({"x": ["A", "B", "C"], "y": [10, 20, 15]})
fig = px.bar(df, x="x", y="y", title="Sample Bar Chart")
display(fig)

# %% Display a table
display(pl.concat([df] * 10))
