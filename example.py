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
1. Markdown rendering
2. Collapsible JSON tree viewer
3. `@nb_cache` caching decorator
4. Auto-detected displays for Polars and Plotly
"""

# %% Imports
import time
from datetime import date

import plotly.express as px
import polars as pl

from nb import HTML, MD, Object, Table, display, nb_cache

# %% Introduction
display(MD("# Welcome to the `nb` runner!"))
display(HTML("<p style='color: #2563eb;'>This HTML text is styled directly.</p>"))

for _ in range(5):
    time.sleep(1)
    display("show something")

display(MD("## Sample numpy"))
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
display(Table(pl.concat([df] * 10)))

# %% Collapsible Object Wrapper
my_data = {
    "project": "nb",
    "version": "0.1.0",
    "features": ["caching", "streaming", "ipc", "Svelte UI"],
    "nested": {"status": "active", "port": 7777, "socket": ".nb.sock"},
}
display(Object(my_data))
display(MD("**Hello**"))

# %% Caching with @nb_cache

WINDOW = 3


@nb_cache(keys=["WINDOW"])
def expensive_computation(x):
    display(MD(f"Calculating for x={x} (this should only run on cache miss)..."))
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
display(Table(pl.concat([df] * 10)))
