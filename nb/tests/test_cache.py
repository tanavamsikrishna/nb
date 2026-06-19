import types

import numpy as np
import polars as pl
import pytest
from pydantic import BaseModel

import nb.framework as fw
from nb.framework import (
    DisplayRecord,
    _cache,
    _check_purity,
    _code_fingerprint,
    _hash_value,
    clear_all_cache,
    clear_cache_by_name,
    display,
    nb_cache,
)


def test_purity_linter() -> None:
    def pure_func(x: int) -> int:
        return x + 1

    _check_purity(pure_func.__code__, "pure_func")

    def impure_func(x: int) -> None:
        global G
        G = x

    with pytest.raises(SyntaxError):
        _check_purity(impure_func.__code__, "impure_func")


def test_hash_value() -> None:
    assert _hash_value(1) == _hash_value(1)
    assert _hash_value("test") != _hash_value("test2")
    assert _hash_value(None) == _hash_value(None)

    arr1 = np.array([1, 2, 3])
    arr2 = np.array([1, 2, 3])
    arr3 = np.array([1, 2, 4])
    assert _hash_value(arr1) == _hash_value(arr2)
    assert _hash_value(arr1) != _hash_value(arr3)

    df1 = pl.DataFrame({"a": [1, 2]})
    df2 = pl.DataFrame({"a": [1, 2]})
    df3 = pl.DataFrame({"a": [1, 3]})
    assert _hash_value(df1) == _hash_value(df2)
    assert _hash_value(df1) != _hash_value(df3)

    class Model(BaseModel):
        val: int

    m1 = Model(val=10)
    m2 = Model(val=10)
    m3 = Model(val=11)
    assert _hash_value(m1) == _hash_value(m2)
    assert _hash_value(m1) != _hash_value(m3)


def _compile_func(src: str) -> types.FunctionType:
    # Compile a top-level `def f(...)` from source and return the function. Using a
    # fixed name `f` lets us compare two source variants without co_name differences.
    ns: dict = {}
    exec(compile(src, "<test>", "exec"), ns)
    return ns["f"]


def test_code_fingerprint() -> None:
    fp = lambda src: _code_fingerprint(_compile_func(src).__code__)

    # Line position is irrelevant: padding the function down the file must not change it.
    assert fp("def f():\n    return 1\n") == fp("\n\n\ndef f():\n    return 1\n")

    # Comments and whitespace-only reformatting are invisible to the code object.
    assert fp("def f(x):\n    # a comment\n    return x + 1\n") == fp(
        "def f(x):\n    return  x+1\n"
    )

    # Constants are part of the key (this is the bug the old co_code-only fallback had).
    assert fp("def f():\n    return 1\n") != fp("def f():\n    return 2\n")

    # Symbol names matter.
    assert fp("def f(a):\n    return a\n") != fp("def f(b):\n    return b\n")

    # Docstrings are intentionally included, so editing one invalidates.
    assert fp('def f():\n    "doc one"\n    return 1\n') != fp(
        'def f():\n    "doc two"\n    return 1\n'
    )

    # Nested string-bodied lambdas must not be mistaken for docstrings and dropped.
    assert fp('def f():\n    return (lambda: "foo")\n') != fp(
        'def f():\n    return (lambda: "bar")\n'
    )


def test_hash_value_functions_are_line_independent() -> None:
    # Notebook-defined functions are hashed via their code fingerprint. A bare lambda
    # whose body is a string is the tricky case: its return value lives in co_consts[0],
    # so the two must hash differently.
    foo = lambda: "foo"
    bar = lambda: "bar"
    foo.__module__ = "__main__"
    bar.__module__ = "__main__"
    assert _hash_value(foo) != _hash_value(bar)

    # Functions outside __main__ remain unhashable.
    def helper() -> int:
        return 1

    helper.__module__ = "somewhere.else"
    with pytest.raises(TypeError):
        _hash_value(helper)


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

    # Clearing by short name removes only matching entries and reports how many
    # distinct functions were cleared.
    cleared, unmatched = clear_cache_by_name(["mult"])
    assert cleared == 1
    assert unmatched == []
    assert len(_cache) == 1

    # A name that matches nothing is a no-op, and is reported as unmatched.
    assert clear_cache_by_name(["does_not_exist"]) == (0, ["does_not_exist"])
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
    assert clear_cache_by_name(["inner"]) == (1, [])
    assert len(_cache) == 1
    assert clear_cache_by_name([inner_qualname]) == (0, [inner_qualname])  # already gone

    # Repopulate both entries (outer is cached too, so it must be cleared for its
    # body — and thus inner — to re-run).
    clear_all_cache()
    outer(5)
    assert len(_cache) == 2

    # The nested function can also be cleared by its full qualname.
    assert clear_cache_by_name([inner_qualname]) == (1, [])


def test_clear_cache_by_name_short_name_collision() -> None:
    clear_all_cache()

    # Two distinct cached functions in different scopes sharing the short name
    # "worker" but doing different things (different source -> different keys).
    def make_a():
        @nb_cache
        def worker(x: int) -> int:
            return x + 1

        return worker

    def make_b():
        @nb_cache
        def worker(x: int) -> int:
            return x + 2

        return worker

    make_a()(0)
    make_b()(0)
    assert len(_cache) == 2

    # The short name clears both — over-clearing is the intended, safe default.
    assert clear_cache_by_name(["worker"]) == (2, [])
    assert len(_cache) == 0


def test_clear_cache_by_name_dedups_and_reports_partial() -> None:
    clear_all_cache()

    @nb_cache
    def kept(x: int) -> int:
        return x

    @nb_cache
    def gone(x: int) -> int:
        return x

    kept(1)
    gone(1)

    # Duplicate names collapse; the one real miss is reported once.
    cleared, unmatched = clear_cache_by_name(["gone", "gone", "typo"])
    assert cleared == 1
    assert unmatched == ["typo"]
    assert len(_cache) == 1


def test_clear_cache_by_name_counts_functions_not_entries() -> None:
    clear_all_cache()

    @nb_cache
    def fetch(x: int) -> int:
        return x

    # One function, three distinct input-sets -> three cache entries.
    fetch(1)
    fetch(2)
    fetch(3)
    assert len(_cache) == 3

    # Clearing reports 1 function (the unit the user thinks in), not 3 entries,
    # even though all three entries are removed.
    cleared, unmatched = clear_cache_by_name(["fetch"])
    assert cleared == 1
    assert unmatched == []
    assert len(_cache) == 0
