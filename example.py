"""
# nb Framework Example Notebook

This notebook demonstrates the capabilities of the `nb` execution and display framework, including:
1. Markdown rendering
2. Collapsible JSON tree viewer
3. `@nb_cache` caching decorator
4. Auto-detected displays for Polars and Plotly
"""

# %%

import functools
import time

from nb import HTML, MD, Object, display, nb_cache

# %% Cell 1: Introduction
display(MD("### Welcome to the `nb` runner!"))
display(HTML("<p style='color: #2563eb;'>This HTML text is styled directly.</p>"))

# %% Cell 2: Collapsible Object Wrapper
my_data = {
    "project": "nb",
    "version": "0.1.0",
    "features": ["caching", "streaming", "ipc", "Svelte UI"],
    "nested": {"status": "active", "port": 7777, "socket": ".nb.sock"},
}
display(Object(my_data))

# %% Cell 3: Caching with @nb_cache

WINDOW = 3


@functools.partial(nb_cache, keys=["WINDOW"])
def expensive_computation(x):
    display(MD(f"Calculating for x={x} (this should only run on cache miss)..."))
    time.sleep(1)  # simulate slow task
    return x * WINDOW


res1 = expensive_computation(10)
display(f"Result 1: {res1}")

# %% Cell 4: Verify Caching Hit
# This call should hit the cache, replay the md display record instantly, and return 30 without sleeping
res2 = expensive_computation(10)
display(f"Result 2: {res2}")
