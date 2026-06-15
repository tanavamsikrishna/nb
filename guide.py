"""
Specification/Documentation
"""

# %% Setup

from datetime import date

import plotly.express as px
import polars as pl

from nb import HTML, MD, Object, display, nb_cache

DATA_MULTIPLIER = 2

# %% <cell level title>

# Showing plain text
display("Running notebook")


# To cache function call returns by keying on the function's input params & the globals passed using the `keys` param. Not allowed to mutate globals in such functions.
@nb_cache(keys=["DATA_MULTIPLIER"])
def get_data(repeat: int) -> pl.DataFrame:
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
    return pl.concat([df] * DATA_MULTIPLIER * repeat)


# %% Demo of datatypes that can be shown

# Markdown -- display a `MD` object
display(MD("# This is a header\n`hi`"))

# HTML -- display a `HTML`
display(HTML("<p style='color: #2563eb;'>This HTML text is styled directly.</p>"))

# polars table -- display a `DataFrame`
display(get_data(3))

# strings -- display a `str`
display("Hello")

# Object (like json, yaml, python dictionary etc) -- display a `Object`
my_data = {
    "project": "nb",
    "version": "0.1.0",
    "features": ["caching", "streaming", "ipc", "Svelte UI"],
}
display(Object(my_data))

# Plotly Display -- display a `Figure`
df = pl.DataFrame({"x": ["A", "B", "C"], "y": [10, 20, 15]})
fig = px.bar(df, x="x", y="y", title="Sample Bar Chart")
display(fig)

# %% Caveats

# `print` statement sends data to stdout and not to the notebook UI
print("logging here")
