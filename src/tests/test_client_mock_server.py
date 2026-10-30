"""Интеграционные тесты клиента против mock_server.

Поднимают локальный HTTP-мок SampleAPIs (без интернета и без responses).
Полезно проверить полный CRUD и fault-сценарии (HTML, обрыв соединения).
"""

from __future__ import annotations

import sys
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.client import SampleApisCoffeeClient
from app.exceptions import CoffeeApiError, CoffeeNotFoundError

MOCK_DIR = Path(__file__).resolve().parents[2] / "mock_server"
if str(MOCK_DIR) not in sys.path:
    sys.path.insert(0, str(MOCK_DIR))

import server as coffee_mock  # noqa: E402

SEED = {
    "hot": [
        {
            "title": "Latte",
            "description": "Milk",
            "ingredients": ["Espresso", "Steamed milk"],
            "image": "https://img/latte",
            "id": 2,
        },
        {
            "title": "Espresso",
            "description": "Strong",
            "ingredients": ["Espresso"],
            "image": "",
            "id": 6,
        },
    ],
    "iced": [],
}

NEW_DRINK = {
    "title": "Group coffee testmark",
    "description": "Hot drink",
    "ingredients": ["Water", "Coffee"],
    "image": "https://example.com/coffee.jpg",
}


@pytest.fixture
def mock_base_url() -> Iterator[str]:
    http_server = coffee_mock.MockServer(
        ("127.0.0.1", 0),
        coffee_mock.Store(SEED),
        faults={},
        slow_seconds=0.5,
        quiet=True,
    )
    port = http_server.server_address[1]
    thread = threading.Thread(
        target=http_server.serve_forever,
        kwargs={"poll_interval": 0.05},
        daemon=True,
    )
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}/coffee/hot"
    finally:
        http_server.shutdown()
        http_server.server_close()


@pytest.fixture
def fault_base_url() -> Iterator[tuple[str, coffee_mock.MockServer]]:
    """Мок с GET=html и DELETE=drop — для проверки обработки сбоев."""
    http_server = coffee_mock.MockServer(
        ("127.0.0.1", 0),
        coffee_mock.Store(SEED),
        faults={"GET": "html", "DELETE": "drop"},
        slow_seconds=0.5,
        quiet=True,
    )
    port = http_server.server_address[1]
    thread = threading.Thread(
        target=http_server.serve_forever,
        kwargs={"poll_interval": 0.05},
        daemon=True,
    )
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}/coffee/hot", http_server
    finally:
        http_server.shutdown()
        http_server.server_close()


def test_crud_roundtrip_on_mock_server(mock_base_url: str) -> None:
    client = SampleApisCoffeeClient(base_url=mock_base_url, timeout=5.0)

    drinks = client.list_drinks()
    assert len(drinks) == 2
    assert drinks[0]["id"] == 2

    created = client.create_drink(NEW_DRINK)
    drink_id = created["id"]
    assert isinstance(drink_id, int)
    assert created["title"] == NEW_DRINK["title"]

    fetched = client.get_drink(drink_id)
    assert fetched["title"] == NEW_DRINK["title"]
    assert fetched["ingredients"] == NEW_DRINK["ingredients"]

    replaced = {
        "title": "Replaced drink",
        "description": "Fully replaced",
        "ingredients": ["Espresso"],
        "image": "https://example.com/replaced.jpg",
    }
    after_put = client.replace_drink(drink_id, replaced)
    assert after_put["title"] == "Replaced drink"
    assert after_put["id"] == drink_id
    assert client.get_drink(drink_id)["description"] == "Fully replaced"

    after_patch = client.update_drink(drink_id, {"description": "Patched only"})
    assert after_patch["description"] == "Patched only"
    assert after_patch["title"] == "Replaced drink"
    again = client.get_drink(drink_id)
    assert again["description"] == "Patched only"
    assert again["title"] == "Replaced drink"

    assert client.delete_drink(drink_id) is None
    with pytest.raises(CoffeeNotFoundError):
        client.get_drink(drink_id)


def test_get_missing_on_mock_server(mock_base_url: str) -> None:
    client = SampleApisCoffeeClient(base_url=mock_base_url, timeout=5.0)
    with pytest.raises(CoffeeNotFoundError):
        client.get_drink(999)


def test_html_fault_raises_api_error(
    fault_base_url: tuple[str, coffee_mock.MockServer],
) -> None:
    base_url, _ = fault_base_url
    client = SampleApisCoffeeClient(base_url=base_url, timeout=5.0)
    with pytest.raises(CoffeeApiError):
        client.list_drinks()


def test_drop_fault_raises_api_error(
    fault_base_url: tuple[str, coffee_mock.MockServer],
) -> None:
    base_url, _ = fault_base_url
    client = SampleApisCoffeeClient(base_url=base_url, timeout=5.0)
    with pytest.raises(CoffeeApiError):
        client.delete_drink(2)
