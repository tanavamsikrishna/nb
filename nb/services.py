"""Simple service locator for dependency injection.

Registers concrete service instances by type and retrieves them with
type-safe accessors. Callers depend on the registered type, not on how
the instance was constructed.

Registry keys:
- External I/O edges (currently `nb.code_diff.CodeDiff`)
- Process-wide singletons wired once at the composition root
  (`nb.daemon.main`, via each service's `register()`)

Non-goals: constructor injection, lifecycle scopes, or automatic wiring.
"""

from typing import cast

__services: dict[type, object] = {}


def get_service[T](service_type: type[T]) -> T:
    try:
        return cast(T, __services[service_type])
    except KeyError as e:
        type_name = getattr(service_type, "__name__", repr(service_type))
        msg = f"Service not registered: {type_name}"
        raise KeyError(msg) from e


def set_service[T](service_type: type[T], service: T) -> None:
    __services[service_type] = service


def clear_services() -> None:
    __services.clear()


def get_all_services_types() -> list[type]:
    return list(__services)
