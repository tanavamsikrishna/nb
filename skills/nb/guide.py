"""
Specification/Documentation

This module-level docstring is rendered as the notebook description in the UI.
"""

# %% Setup

from datetime import date

import plotly.express as px
import polars as pl

from nb import display, nb_cache

DATA_MULTIPLIER = 2

# %% <cell level title>

# Showing plain text
display("Running notebook")


# Bare @nb_cache -- cache key derived from function source + args only (no globals)
@nb_cache
def get_raw() -> pl.DataFrame:
    return pl.DataFrame({"x": [1, 2, 3]})


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
#
# `display(obj, *, as_=..., floating_point_accuracy=4, label=None)` is overloaded.
# The keyword-only `as_` selects the render type explicitly; when omitted, the type
# is auto-detected. `as_` is spelled with a trailing underscore because `as` is a
# reserved word. Valid values: "md", "html", "text", "table", "object".

# Markdown -- pass `as_="md"`
display("# This is a header\n`hi`", as_="md")

# HTML -- pass `as_="html"`
display("<p style='color: green;'>This HTML text is styled directly.</p>", as_="html")

# polars table -- a `DataFrame` is auto-detected as a table
display(get_data(3))

# Table options -- floating_point_accuracy and label are display() kwargs
# (as_="table" is optional here since a DataFrame is auto-detected)
display(get_data(1), floating_point_accuracy=2, label="My Table")

# strings -- a `str` is auto-detected as plain text
display("Hello")

# Object (json, yaml, python dict, pydantic model, etc.) -- any non-str, non-special
# value auto-detects as an object (JSON-serialized, shown in a collapsible tree).
# Pass as_="object" to force it (e.g. to render a str as a JSON object).
# Serialization happens at display() time — later mutations are not visible.
my_data = {
    "project": "nb",
    "version": "0.1.0",
    "features": ["caching", "streaming", "ipc", "Svelte UI"],
}
display(my_data)

# Plotly Display -- display a `Figure`
df = pl.DataFrame({"x": ["A", "B", "C"], "y": [10, 20, 15]})
fig = px.bar(df, x="x", y="y", title="Sample Bar Chart")
display(fig)

# Altair Display -- display an `alt.Chart`
# import altair as alt
# chart = alt.Chart(df).mark_bar().encode(x="x", y="y")
# display(chart)

# %% Caveats

# `print` statement sends data to stdout and not to the notebook UI
print("logging here")
