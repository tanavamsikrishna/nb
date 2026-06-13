import pytest
import numpy as np
import polars as pl
from pydantic import BaseModel
import nb.framework as fw
from nb.framework import DisplayRecord, MD, _check_purity, _hash_value, display, nb_cache, _cache, clear_cache

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
    clear_cache()
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
    clear_cache()
    emitted: list[DisplayRecord] = []
    old_emitter = fw._active_emitter
    fw._active_emitter = emitted.append
    call_count = 0

    try:
        @nb_cache
        def greet(name: str) -> str:
            nonlocal call_count
            call_count += 1
            display(MD(f"Hello {name}"))
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
    clear_cache()
    
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

def test_clear_cache() -> None:
    clear_cache()

    @nb_cache
    def mult(x: int, y: int) -> int:
        return x * y

    mult(2, 3)
    assert len(_cache) == 1

    clear_cache(mult)
    assert len(_cache) == 0
