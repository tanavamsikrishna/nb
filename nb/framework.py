import dis
import hashlib
import inspect
import json
import pickle
import types
from dataclasses import dataclass
from functools import wraps
from typing import Any, Callable, Literal, TypeVar, cast, overload

F = TypeVar("F", bound=Callable)


@dataclass
class DisplayRecord:
    type: str
    payload: Any


@dataclass
class CacheEntry:
    result: Any
    display_records: list[DisplayRecord]
    name: str = ""
    qualname: str = ""


# Cache state location
_cache: dict[str, CacheEntry] = {}

# Active emitter callback set by daemon
_active_emitter: Callable[[DisplayRecord], None] | None = None
_current_cell_id: int | None = None


def _emit(record: DisplayRecord) -> None:
    if _active_emitter is not None:
        _active_emitter(record)


def _serialize_table(df: Any, floating_point_accuracy: int = 4, label: str | None = None) -> dict:
    import base64
    import io

    buf = io.BytesIO()
    df.write_parquet(buf, compression="snappy")
    return {
        "data": base64.b64encode(buf.getvalue()).decode(),
        "total_rows": len(df),
        "floating_point_accuracy": floating_point_accuracy,
        "label": label,
    }


def _serialize_object(obj: Any) -> Any:
    if hasattr(obj, "model_dump") and callable(obj.model_dump):
        obj = obj.model_dump()

    try:
        return json.loads(json.dumps(obj))
    except TypeError as exc:
        raise TypeError(f"Object display payload is not JSON serializable: {type(obj)!r}") from exc


def _create_display_record(
    obj: Any,
    as_: str | None = None,
    *,
    floating_point_accuracy: int = 4,
    label: str | None = None,
) -> DisplayRecord:
    # Explicit type selection via `as_`
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
                payload=_serialize_table(obj, floating_point_accuracy, label),
            )
        raise ValueError(f"Unknown display type as_={as_!r}")

    # Auto-detect when `as_` is omitted
    # 1. Plotly
    try:
        from plotly.basedatatypes import BaseFigure

        if isinstance(obj, BaseFigure):
            return DisplayRecord(type="plotly", payload=json.loads(obj.to_json()))
    except (ImportError, AttributeError):
        pass

    # 2. Altair
    try:
        import altair as alt

        if isinstance(obj, alt.TopLevelMixin):
            return DisplayRecord(type="altair", payload=obj.to_dict())
    except (ImportError, AttributeError):
        pass

    # 3. Polars DataFrame -> table
    try:
        import polars as pl

        if isinstance(obj, pl.DataFrame):
            return DisplayRecord(
                type="table",
                payload=_serialize_table(obj, floating_point_accuracy, label),
            )
    except ImportError:
        pass

    # 4. Plain strings -> text
    if isinstance(obj, str):
        return DisplayRecord(type="text", payload=obj)

    # 5. Fallback: everything else -> object
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
    floating_point_accuracy: int = ...,
    label: str | None = ...,
) -> None: ...
def display(
    obj: Any,
    *,
    as_: Literal["md", "html", "text", "object", "table"] | None = None,
    floating_point_accuracy: int = 4,
    label: str | None = None,
) -> None:
    _emit(
        _create_display_record(
            obj, as_, floating_point_accuracy=floating_point_accuracy, label=label
        )
    )


# Type-dispatch hashing
def _hash_value(obj: Any) -> bytes:
    # Primitives
    if isinstance(obj, (int, str, float, bool, bytes, type(None))):
        return pickle.dumps(obj)

    # Polars DataFrame
    try:
        import polars as pl

        if isinstance(obj, pl.DataFrame):
            # hash_rows() + schema bytes
            row_hashes = obj.hash_rows().to_numpy().tobytes()
            schema_bytes = str(obj.schema).encode("utf-8")
            return row_hashes + schema_bytes
    except ImportError:
        pass

    # Numpy ndarray
    try:
        import numpy as np

        if isinstance(obj, np.ndarray):
            return obj.tobytes() + str(obj.dtype).encode("utf-8") + str(obj.shape).encode("utf-8")
    except ImportError:
        pass

    # Pydantic BaseModel
    try:
        from pydantic import BaseModel

        if isinstance(obj, BaseModel):
            if hasattr(obj, "model_dump_json") and callable(obj.model_dump_json):
                return obj.model_dump_json().encode("utf-8")
            elif hasattr(obj, "json") and callable(obj.json):
                return obj.json().encode("utf-8")
    except ImportError:
        pass

    # Notebook-defined functions
    if isinstance(obj, (types.FunctionType, types.MethodType)):
        if getattr(obj, "__module__", None) == "__main__":
            try:
                return inspect.getsource(obj).encode("utf-8")
            except Exception:
                # If we cannot get source, hash the bytecode
                if hasattr(obj, "__code__"):
                    return pickle.dumps(obj.__code__.co_code)
                raise TypeError(f"Could not hash notebook-defined function {obj}")
        else:
            raise TypeError(f"Functions defined outside __main__ are not hashable: {obj}")

    raise TypeError(f"Type {type(obj)} is not hashable for cache key computation")


def compute_key(func: Callable, args: tuple, kwargs: dict, keys: list[str] | None) -> str:
    h = hashlib.blake2b()

    # 1. Source code hash of the function
    try:
        source_code = inspect.getsource(func)
    except Exception:
        # Fallback to bytecode if getsource fails
        source_code = func.__code__.co_code.hex()
    h.update(source_code.encode("utf-8"))

    # 2. Input hash (args, kwargs sorted by key)
    for arg in args:
        h.update(_hash_value(arg))
    for k in sorted(kwargs.keys()):
        h.update(k.encode("utf-8"))
        h.update(_hash_value(kwargs[k]))

    # 3. Globals hash (when keys is provided)
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


def nb_cache(func: F | None = None, *, keys: list[str] | None = None) -> F:
    def decorator(func: F) -> F:
        # Run purity linter before wrapping
        _check_purity(func.__code__, func.__name__)

        _capture_stack: list[list[DisplayRecord]] = []

        def nb_display(
            obj: Any,
            *,
            as_: str | None = None,
            floating_point_accuracy: int = 4,
            label: str | None = None,
        ) -> None:
            record = _create_display_record(
                obj, as_, floating_point_accuracy=floating_point_accuracy, label=label
            )
            if _capture_stack:
                _capture_stack[-1].append(record)
            _emit(record)

        new_globals = func.__globals__.copy()
        new_globals["display"] = nb_display

        new_func = types.FunctionType(
            func.__code__, new_globals, func.__name__, func.__defaults__, func.__closure__
        )

        @wraps(func)
        def wrapper(*args, **kwargs):
            # Sync any new or modified variables from original globals into the captured globals
            for k, v in func.__globals__.items():
                if k != "display":
                    new_globals[k] = v

            cache_key = compute_key(new_func, args, kwargs, keys)

            if cache_key in _cache:
                entry = _cache[cache_key]
                for record in entry.display_records:
                    _emit(record)
                return entry.result

            records: list[DisplayRecord] = []
            _capture_stack.append(records)
            try:
                result = new_func(*args, **kwargs)
            finally:
                _capture_stack.pop()

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
