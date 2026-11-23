"""Service locator: register by type, retrieve by type."""

import pytest

from nb.services import (
    clear_services,
    get_all_services_types,
    get_service,
    set_service,
)


@pytest.fixture
def registry():
    saved = [(t, get_service(t)) for t in get_all_services_types()]
    clear_services()
    yield
    clear_services()
    for service_type, service in saved:
        set_service(service_type, service)


def test_missing_service_names_the_type(registry) -> None:
    with pytest.raises(KeyError, match="Service not registered: int"):
        get_service(int)


def test_set_then_get_roundtrip(registry) -> None:
    set_service(int, 7)
    assert get_service(int) == 7
    assert get_all_services_types() == [int]


def test_clear_services(registry) -> None:
    set_service(str, "x")
    clear_services()
    assert get_all_services_types() == []
