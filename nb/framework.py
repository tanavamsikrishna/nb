import dis
import hashlib
import json
import pickle
import types
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from typing import Any, Callable, Generator, Literal, TypeVar, cast, overload

import msgspec

F = TypeVar("F", bound=Callable)


class DisplayRecord(msgspec.Struct):
    type: str
    payload: Any


class CacheEntry(msgspec.Struct):
    result: Any
    display_records: list[DisplayRecord]
    name: str = ""
    qualname: str = ""


_cache: dict[str, CacheEntry] = {}

# Set by the daemon for the duration of a run; display primitives emit through it.
_active_emitter: Callable[[DisplayRecord], None] | None = None
_current_cell_id: int | None = None


def _emit(record: DisplayRecord) -> None:
    if _active_emitter is not None:
        _active_emitter(record)


# Where display records currently flow. At the top level it is the live stream
# (_emit); inside an @nb_cache call it is a capturing sink that appends the record
# to that call's frame *and*, by delegating to its parent, to every enclosing
# cache frame — before reaching _emit exactly once. So a record displayed at any
# depth lands in every ancestor's cache entry, making a cache hit reproduce a
# fresh run's output at every nesting level. ContextVar (not a plain global) keeps
# this correct under the daemon's executor thread and auto-restores via the token.
_sink: ContextVar[Callable[[DisplayRecord], None]] = ContextVar("_sink", default=_emit)


@contextmanager
def _capture_into(frame: list[DisplayRecord]) -> Generator[None, None, None]:
    """Route display records into ``frame`` (and all ancestor frames) for the block."""
    parent = _sink.get()

    def sink(record: DisplayRecord) -> None:
        frame.append(record)
        parent(record)

    token = _sink.set(sink)
    try:
        yield
    finally:
        _sink.reset(token)


def _serialize_table(df: Any, label: str | None = None) -> dict:
    import base64
    import io

    buf = io.BytesIO()
    df.write_parquet(buf, compression="snappy")
    return {
        "data": base64.b64encode(buf.getvalue()).decode(),
        "total_rows": len(df),
        "label": label,
    }


def _serialize_object(obj: Any) -> Any:
    if isinstance(obj, msgspec.Struct):
        return json.loads(msgspec.json.encode(obj))

    try:
        return json.loads(json.dumps(obj))
    except TypeError as exc:
        raise TypeError(f"Object display payload is not JSON serializable: {type(obj)!r}") from exc


def _create_display_record(
    obj: Any,
    as_: str | None = None,
    *,
    label: str | None = None,
) -> DisplayRecord:
    if as_ is not None:
        if as_ == "md":
            return DisplayRecord(type="md", payload=str(obj))
        if as_ == "html":
            return DisplayRecord(type="html", payload=str(obj))
        if as_ == "text":
            return DisplayRecord(type="text", payload=str(obj))
        if as_ == "object":
            return DisplayRecord(type="object", payload=_serialize_object(obj))
        if as_ == "table":
            return DisplayRecord(
                type="table",
                payload=_serialize_table(obj, label),
            )
        raise ValueError(f"Unknown display type as_={as_!r}")

    # Auto-detect: the optional deps are imported lazily so the framework works
    # without them installed; a missing one just falls through to the next type.
    try:
        from plotly.basedatatypes import BaseFigure

        if isinstance(obj, BaseFigure):
            return DisplayRecord(type="plotly", payload=json.loads(cast(str, obj.to_json())))
    except (ImportError, AttributeError):
        pass

    try:
        import altair as alt

        if isinstance(obj, alt.TopLevelMixin):
            return DisplayRecord(type="altair", payload=obj.to_dict())
    except (ImportError, AttributeError):
        pass

    try:
        import polars as pl

        if isinstance(obj, pl.DataFrame):
            return DisplayRecord(
                type="table",
                payload=_serialize_table(obj, label),
            )
    except ImportError:
        pass

    if isinstance(obj, str):
        return DisplayRecord(type="text", payload=obj)

    return DisplayRecord(type="object", payload=_serialize_object(obj))


@overload
def display(obj: Any) -> None: ...
@overload
def display(obj: str, *, as_: Literal["md", "html", "text"]) -> None: ...
@overload
def display(obj: Any, *, as_: Literal["object"]) -> None: ...
@overload
def display(
    obj: Any,
    *,
    as_: Literal["table"] = ...,
    label: str | None = ...,
) -> None: ...
def display(
    obj: Any,
    *,
    as_: Literal["md", "html", "text", "object", "table"] | None = None,
    label: str | None = None,
) -> None:
    _sink.get()(_create_display_record(obj, as_, label=label))


def params(**kwargs: Any) -> None:
    """Record experiment hyperparameters.

    Like ``display`` it emits through the active sink, so the values are rendered
    live (as a key/value table), captured/replayed by ``@nb_cache``, and folded
    into the daemon's cell state — but it produces a distinct ``"params"`` record
    so experiment tracking can collect them separately from ordinary output.
    """
    _sink.get()(DisplayRecord(type="params", payload=_serialize_object(kwargs)))


def _code_fingerprint(code: types.CodeType) -> bytes:
    # A line-number-independent fingerprint of a code object's logic. We hash the
    # opcodes, signature shape, symbol names, and constants (recursing into nested
    # code objects for closures/lambdas/comprehensions), while deliberately
    # excluding positional metadata (co_firstlineno, co_filename, co_linetable).
    # Comments never reach the code object so they are ignored for free; docstrings
    # live in co_consts and are intentionally kept (changing one invalidates the
    # cache) to avoid special-casing that would mis-handle string-bodied lambdas.
    h = hashlib.blake2b()
    h.update(code.co_code)
    h.update(
        pickle.dumps(
            (
                code.co_name,
                code.co_argcount,
                code.co_posonlyargcount,
                code.co_kwonlyargcount,
                code.co_flags,
                code.co_names,
                code.co_varnames,
                code.co_freevars,
                code.co_cellvars,
            )
        )
    )
    for const in code.co_consts:
        if isinstance(const, types.CodeType):
            h.update(b"\x00CODE")
            h.update(_code_fingerprint(const))
        else:
            h.update(b"\x00CONST")
            h.update(pickle.dumps(const))
    return h.digest()


def _hash_value(obj: Any) -> bytes:
    if isinstance(obj, (int, str, float, bool, bytes, type(None))):
        return pickle.dumps(obj)

    try:
        import polars as pl

        if isinstance(obj, pl.DataFrame):
            row_hashes = obj.hash_rows().to_numpy().tobytes()
            schema_bytes = str(obj.schema).encode("utf-8")
            return row_hashes + schema_bytes
    except ImportError:
        pass

    try:
        import numpy as np

        if isinstance(obj, np.ndarray):
            return obj.tobytes() + str(obj.dtype).encode("utf-8") + str(obj.shape).encode("utf-8")
    except ImportError:
        pass

    if isinstance(obj, msgspec.Struct):
        return msgspec.json.encode(obj)

    # Only notebook-defined functions are hashable: their logic lives in the
    # notebook, so a change to it should invalidate the cache.
    if isinstance(obj, (types.FunctionType, types.MethodType)):
        if getattr(obj, "__module__", None) == "__main__":
            return _code_fingerprint(obj.__code__)
        else:
            raise TypeError(f"Functions defined outside __main__ are not hashable: {obj}")

    raise TypeError(f"Type {type(obj)} is not hashable for cache key computation")


def compute_key(func: Callable, args: tuple, kwargs: dict, keys: list[str] | None) -> str:
    h = hashlib.blake2b()

    h.update(_code_fingerprint(func.__code__))

    for arg in args:
        h.update(_hash_value(arg))
    for k in sorted(kwargs.keys()):
        h.update(k.encode("utf-8"))
        h.update(_hash_value(kwargs[k]))

    if keys is not None:
        for key in keys:
            if key not in func.__globals__:
                raise KeyError(
                    f"Global variable '{key}' specified in keys is missing from globals."
                )
            val = func.__globals__[key]
            h.update(key.encode("utf-8"))
            h.update(_hash_value(val))

    return h.hexdigest()


def _check_purity(code: types.CodeType, func_name: str) -> None:
    for instr in dis.get_instructions(code):
        if instr.opname in ("STORE_GLOBAL", "DELETE_GLOBAL"):
            raise SyntaxError(
                f"@nb_cache '{func_name}' assigns to global '{instr.argval}'. "
                f"@nb_cache functions must be pure."
            )
        elif instr.opname == "LOAD_CONST" and isinstance(instr.argval, types.CodeType):
            _check_purity(instr.argval, func_name)


@overload
def nb_cache(func: F) -> F: ...
@overload
def nb_cache(*, keys: list[str] | None = None) -> Callable[[F], F]: ...
def nb_cache(func: F | None = None, *, keys: list[str] | None = None) -> F | Callable[[F], F]:
    # Known limitation: a set/frozenset *constant* in the function body lands in
    # co_consts and is pickled by _code_fingerprint. pickle.dumps serializes set
    # elements in iteration order, which for str/bytes depends on PYTHONHASHSEED,
    # so the key is only stable within a single process. Harmless today because the
    # cache is in-memory and dies with the daemon (a restart clears it anyway) — but
    # if entries are ever persisted across processes, canonicalize (sort) set
    # elements before hashing, since equal sets could otherwise key differently.
    def decorator(func: F) -> F:
        _check_purity(func.__code__, func.__name__)

        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            cache_key = compute_key(func, args, kwargs, keys)

            if cache_key in _cache:
                entry = _cache[cache_key]
                # Replay through the *current* sink, not _emit directly: a nested
                # hit must feed its records into the enclosing cache frame(s) too,
                # so an outer entry built while this call was a hit still records
                # (and later replays) what this call produced.
                sink = _sink.get()
                for record in entry.display_records:
                    sink(record)
                return entry.result

            records: list[DisplayRecord] = []
            with _capture_into(records):
                result = func(*args, **kwargs)

            _cache[cache_key] = CacheEntry(
                result=result,
                display_records=records,
                name=func.__name__,
                qualname=func.__qualname__,
            )
            return result

        return cast(F, wrapper)

    if func is not None:
        return decorator(func)
    return decorator


def clear_all_cache() -> None:
    _cache.clear()


def clear_cache_by_name(names: list[str]) -> tuple[int, list[str]]:
    """Drop every cache entry whose function name or qualname is in ``names``.

    Matching on either the short ``__name__`` or the full ``__qualname__`` means a
    nested function (qualname ``outer.<locals>.inner``) can be cleared by passing
    just ``inner``. A short name clears every entry sharing it, across all scopes;
    pass the qualname to target a single function.

    Returns ``(functions_cleared, unmatched_names)``. ``functions_cleared`` counts
    distinct qualnames removed — i.e. how many *functions* were cleared, not how
    many cache entries (a function may have many entries, one per input-set), since
    that is the unit a notebook author thinks in. ``unmatched_names`` lists the
    requested names that matched no entry (useful for surfacing typos). Names are
    de-duplicated while preserving their given order.
    """
    targets = list(dict.fromkeys(names))
    target_set = set(targets)
    matched: set[str] = set()
    cleared_qualnames: set[str] = set()
    to_remove: list = []
    for k, e in _cache.items():
        hits = target_set.intersection((e.name, e.qualname))
        if hits:
            to_remove.append(k)
            matched |= hits
            cleared_qualnames.add(e.qualname)
    for k in to_remove:
        _cache.pop(k, None)
    unmatched = [n for n in targets if n not in matched]
    return len(cleared_qualnames), unmatched
