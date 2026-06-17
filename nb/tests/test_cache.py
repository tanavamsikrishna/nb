import numpy as np
import polars as pl
import pytest
from pydantic import BaseModel

import nb.framework as fw
from nb.framework import (
    DisplayRecord,
    _cache,
    _check_purity,
    _hash_value,
    clear_all_cache,
    clear_cache_by_name,
    display,
    nb_cache,
)


def test_purity_linter() -> None:
    # Pure function should pass
    def pure_func(x: int) -> int:
        return x + 1

    _check_purity(pure_func.__code__, "pure_func")

    # Impure function (mutates global) should raise SyntaxError
    def impure_func(x: int) -> None:
        global G
        G = x

    with pytest.raises(SyntaxError):
        _check_purity(impure_func.__code__, "impure_func")


def test_hash_value() -> None:
    # Primitives
    assert _hash_value(1) == _hash_value(1)
    assert _hash_value("test") != _hash_value("test2")
    assert _hash_value(None) == _hash_value(None)

    # Numpy array
    arr1 = np.array([1, 2, 3])
    arr2 = np.array([1, 2, 3])
    arr3 = np.array([1, 2, 4])
    assert _hash_value(arr1) == _hash_value(arr2)
    assert _hash_value(arr1) != _hash_value(arr3)

    # Polars DataFrame
    df1 = pl.DataFrame({"a": [1, 2]})
    df2 = pl.DataFrame({"a": [1, 2]})
    df3 = pl.DataFrame({"a": [1, 3]})
    assert _hash_value(df1) == _hash_value(df2)
    assert _hash_value(df1) != _hash_value(df3)

    # Pydantic BaseModel
    class Model(BaseModel):
        val: int

    m1 = Model(val=10)
    m2 = Model(val=10)
    m3 = Model(val=11)
    assert _hash_value(m1) == _hash_value(m2)
    assert _hash_value(m1) != _hash_value(m3)


def test_nb_cache_decorator() -> None:
    clear_all_cache()
    call_count = 0

    @nb_cache
    def add(x: int, y: int) -> int:
        nonlocal call_count
        call_count += 1
        return x + y

    assert add(2, 3) == 5
    assert call_count == 1

    # Second call must be a cache hit
    assert add(2, 3) == 5
    assert call_count == 1

    # Different inputs must cause cache miss
    assert add(2, 4) == 6
    assert call_count == 2


def test_nb_cache_captures_and_replays_display() -> None:
    clear_all_cache()
    emitted: list[DisplayRecord] = []
    old_emitter = fw._active_emitter
    fw._active_emitter = emitted.append
    call_count = 0

    try:

        @nb_cache
        def greet(name: str) -> str:
            nonlocal call_count
            call_count += 1
            display(f"Hello {name}", as_="md")
            return name.upper()

        assert greet("Ada") == "ADA"
        assert call_count == 1
        assert emitted == [DisplayRecord(type="md", payload="Hello Ada")]

        emitted.clear()
        assert greet("Ada") == "ADA"
        assert call_count == 1
        assert emitted == [DisplayRecord(type="md", payload="Hello Ada")]
    finally:
        fw._active_emitter = old_emitter


def test_nb_cache_keys() -> None:
    clear_all_cache()

    # Establish globals in the module level for testing
    global WINDOW
    WINDOW = 5
    call_count = 0

    @nb_cache(keys=["WINDOW"])
    def get_windowed_value(x: int) -> int:
        nonlocal call_count
        call_count += 1
        return x + WINDOW

    assert get_windowed_value(10) == 15
    assert call_count == 1

    # Cache hit
    assert get_windowed_value(10) == 15
    assert call_count == 1

    # Change the registered global to trigger cache invalidation
    WINDOW = 10
    assert get_windowed_value(10) == 20
    assert call_count == 2


def test_clear_cache_by_name() -> None:
    clear_all_cache()

    @nb_cache
    def mult(x: int, y: int) -> int:
        return x * y

    @nb_cache
    def add(x: int, y: int) -> int:
        return x + y

    mult(2, 3)
    add(2, 3)
    assert len(_cache) == 2

    # Clearing by short name removes only matching entries and reports the count.
    removed = clear_cache_by_name(["mult"])
    assert removed == 1
    assert len(_cache) == 1

    # A name that matches nothing is a no-op.
    assert clear_cache_by_name(["does_not_exist"]) == 0
    assert len(_cache) == 1


def test_clear_cache_by_name_nested() -> None:
    clear_all_cache()

    @nb_cache
    def outer(x: int) -> int:
        @nb_cache
        def inner(y: int) -> int:
            return y * 2

        return inner(x) + 1

    outer(5)
    # Two entries: outer and the nested inner.
    assert len(_cache) == 2

    inner_qualname = f"{outer.__qualname__}.<locals>.inner"

    # The nested function can be cleared by its short name, without calling
    # anything inside outer.
    assert clear_cache_by_name(["inner"]) == 1
    assert len(_cache) == 1
    assert clear_cache_by_name([inner_qualname]) == 0  # already gone

    # Repopulate both entries (outer is cached too, so it must be cleared for its
    # body — and thus inner — to re-run).
    clear_all_cache()
    outer(5)
    assert len(_cache) == 2

    # The nested function can also be cleared by its full qualname.
    assert clear_cache_by_name([inner_qualname]) == 1
