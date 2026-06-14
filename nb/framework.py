import dis
import hashlib
import inspect
import json
import pickle
import types
from dataclasses import dataclass
from functools import wraps
from typing import Any, Callable, TypeVar, cast

F = TypeVar("F", bound=Callable)


@dataclass
class DisplayRecord:
    type: str
    payload: Any


@dataclass
class CacheEntry:
    result: Any
    display_records: list[DisplayRecord]


# Cache state location
_cache: dict[str, CacheEntry] = {}

# Active emitter callback set by daemon
_active_emitter: Callable[[DisplayRecord], None] | None = None
_current_cell_id: int | None = None


def _emit(record: DisplayRecord) -> None:
    if _active_emitter is not None:
        _active_emitter(record)


# Wrapper types
class MD:
    def __init__(self, text: str):
        self.text = text


class HTML:
    def __init__(self, text: str):
        self.text = text


class Object:
    def __init__(self, obj: Any):
        self.obj = obj


@dataclass
class Table:
    """Wrapper for Polars DataFrames to enable interactive table display."""

    df: Any  # pl.DataFrame — typed as Any to avoid hard import at module level


def _serialize_table(obj: Table) -> dict:
    import base64
    import io

    buf = io.BytesIO()
    obj.df.write_parquet(buf, compression="snappy")
    return {
        "data": base64.b64encode(buf.getvalue()).decode(),
        "total_rows": len(obj.df),
    }


def _serialize_object(obj: Any) -> Any:
    if hasattr(obj, "model_dump") and callable(obj.model_dump):
        obj = obj.model_dump()

    try:
        return json.loads(json.dumps(obj))
    except TypeError as exc:
        raise TypeError(f"Object display payload is not JSON serializable: {type(obj)!r}") from exc


def _create_display_record(obj: Any) -> DisplayRecord:
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

    # 3. Table wrapper (must come before plain Polars DataFrame)
    if isinstance(obj, Table):
        return DisplayRecord(type="table", payload=_serialize_table(obj))

    # 4. Polars
    try:
        import polars as pl

        if isinstance(obj, pl.DataFrame):
            return DisplayRecord(type="html", payload=obj._repr_html_())
    except ImportError:
        pass

    # 5. MD Wrapper
    if isinstance(obj, MD):
        return DisplayRecord(type="md", payload=obj.text)

    # 6. HTML Wrapper
    if isinstance(obj, HTML):
        return DisplayRecord(type="html", payload=obj.text)

    # 7. Object Wrapper
    if isinstance(obj, Object):
        return DisplayRecord(type="object", payload=_serialize_object(obj.obj))

    # Fallback
    return DisplayRecord(type="text", payload=repr(obj))


def display(obj: Any) -> None:
    _emit(_create_display_record(obj))


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

        def nb_display(obj):
            record = _create_display_record(obj)
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

            # Store the cache keys generated by this wrapper for clear_cache(func)
            if not hasattr(wrapper, "_cache_keys"):
                wrapper._cache_keys = set()
            wrapper._cache_keys.add(cache_key)

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

            _cache[cache_key] = CacheEntry(result=result, display_records=records)
            return result

        return cast(F, wrapper)

    if func is not None:
        return decorator(func)
    return decorator


def clear_cache(func: Any = None) -> None:
    if func is None:
        _cache.clear()
    else:
        if hasattr(func, "_cache_keys"):
            for k in func._cache_keys:
                _cache.pop(k, None)
            func._cache_keys.clear()
