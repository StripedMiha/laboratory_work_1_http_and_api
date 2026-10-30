"""Общие фикстуры для тестов клиента.

Тесты используют библиотеку `responses` и не ходят в реальный SampleAPIs.
Реализуйте `SampleApisCoffeeClient`, пока `pytest` не станет зелёным.
"""

from __future__ import annotations

import pytest

from app.client import SampleApisCoffeeClient
from tests.constants import BASE_URL


@pytest.fixture
def client() -> SampleApisCoffeeClient:
    return SampleApisCoffeeClient(base_url=BASE_URL, timeout=5.0)


@pytest.fixture
def drink_payload() -> dict[str, object]:
    return {
        "title": "Group coffee ab12cd34",
        "description": "Hot drink",
        "ingredients": ["Water", "Coffee"],
        "image": "https://example.com/coffee.jpg",
    }
