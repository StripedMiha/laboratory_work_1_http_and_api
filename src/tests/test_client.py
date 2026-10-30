"""TDD-спецификация для SampleApisCoffeeClient (unit, через responses).

Запускайте: pytest
Все тесты должны стать зелёными после реализации клиента.

Поведение статусов и тел сверено с mock_server (локальный мок SampleAPIs).
Интеграция против живого мока — в test_client_mock_server.py.
"""

from __future__ import annotations

import pytest
import requests
import responses
from responses import matchers

from app.client import SampleApisCoffeeClient
from app.exceptions import CoffeeApiError, CoffeeNotFoundError
from tests.constants import BASE_URL, SAMPLE_DRINK


# --- инициализация ---------------------------------------------------------


def test_default_base_url_and_timeout() -> None:
    client = SampleApisCoffeeClient()
    assert client._base_url == "https://api.sampleapis.com/coffee/hot"
    assert client._timeout == 10.0


def test_base_url_strips_trailing_slash() -> None:
    client = SampleApisCoffeeClient(base_url=f"{BASE_URL}/")
    assert client._base_url == BASE_URL


# --- list_drinks -----------------------------------------------------------


@responses.activate
def test_list_drinks_returns_parsed_json(client: SampleApisCoffeeClient) -> None:
    responses.add(
        responses.GET,
        BASE_URL,
        json=[SAMPLE_DRINK],
        status=200,
        content_type="application/json",
    )

    drinks = client.list_drinks()

    assert drinks == [SAMPLE_DRINK]
    assert len(responses.calls) == 1
    assert responses.calls[0].request.method == "GET"
    assert responses.calls[0].request.url == BASE_URL


# --- get_drink -------------------------------------------------------------


@responses.activate
def test_get_drink_returns_object(client: SampleApisCoffeeClient) -> None:
    responses.add(
        responses.GET,
        f"{BASE_URL}/42",
        json=SAMPLE_DRINK,
        status=200,
        content_type="application/json",
    )

    assert client.get_drink(42) == SAMPLE_DRINK


@responses.activate
def test_get_drink_404_raises_not_found(client: SampleApisCoffeeClient) -> None:
    responses.add(
        responses.GET,
        f"{BASE_URL}/999",
        json={},
        status=404,
        content_type="application/json",
    )

    with pytest.raises(CoffeeNotFoundError):
        client.get_drink(999)


# --- create_drink ----------------------------------------------------------


@responses.activate
def test_create_drink_posts_json_and_returns_body(
    client: SampleApisCoffeeClient,
    drink_payload: dict[str, object],
) -> None:
    created = {**drink_payload, "id": 7}
    responses.add(
        responses.POST,
        BASE_URL,
        json=created,
        status=201,
        content_type="application/json",
        match=[matchers.json_params_matcher(drink_payload)],
    )

    result = client.create_drink(drink_payload)

    assert result == created
    assert result["id"] == 7
    assert responses.calls[0].request.method == "POST"


@responses.activate
def test_create_drink_accepts_200(
    client: SampleApisCoffeeClient,
    drink_payload: dict[str, object],
) -> None:
    created = {**drink_payload, "id": 8}
    responses.add(
        responses.POST,
        BASE_URL,
        json=created,
        status=200,
        content_type="application/json",
    )

    assert client.create_drink(drink_payload)["id"] == 8


# --- replace_drink (PUT) ---------------------------------------------------


@responses.activate
def test_replace_drink_puts_full_payload(
    client: SampleApisCoffeeClient,
    drink_payload: dict[str, object],
) -> None:
    replaced = {**drink_payload, "title": "Replaced", "id": 42}
    responses.add(
        responses.PUT,
        f"{BASE_URL}/42",
        json=replaced,
        status=200,
        content_type="application/json",
        match=[matchers.json_params_matcher(replaced)],
    )

    assert client.replace_drink(42, replaced) == replaced
    assert responses.calls[0].request.method == "PUT"


# --- update_drink (PATCH) --------------------------------------------------


@responses.activate
def test_update_drink_patches_partial_changes(
    client: SampleApisCoffeeClient,
) -> None:
    changes = {"description": "Updated only"}
    updated = {**SAMPLE_DRINK, **changes}
    responses.add(
        responses.PATCH,
        f"{BASE_URL}/42",
        json=updated,
        status=200,
        content_type="application/json",
        match=[matchers.json_params_matcher(changes)],
    )

    assert client.update_drink(42, changes) == updated
    assert responses.calls[0].request.method == "PATCH"


# --- delete_drink ----------------------------------------------------------


@responses.activate
def test_delete_drink_success_with_empty_json_object(
    client: SampleApisCoffeeClient,
) -> None:
    """Как в SampleAPIs / mock_server: DELETE → 200 и тело {}."""
    responses.add(
        responses.DELETE,
        f"{BASE_URL}/42",
        json={},
        status=200,
        content_type="application/json",
    )

    assert client.delete_drink(42) is None


@responses.activate
def test_delete_drink_success_without_json_body(
    client: SampleApisCoffeeClient,
) -> None:
    """Клиент не должен требовать JSON-тело на успешный DELETE."""
    responses.add(
        responses.DELETE,
        f"{BASE_URL}/42",
        status=200,
        body="",
        content_type="text/plain",
    )

    assert client.delete_drink(42) is None


@responses.activate
def test_delete_drink_404_raises_not_found(client: SampleApisCoffeeClient) -> None:
    responses.add(
        responses.DELETE,
        f"{BASE_URL}/42",
        json={},
        status=404,
        content_type="application/json",
    )

    with pytest.raises(CoffeeNotFoundError):
        client.delete_drink(42)


# --- ошибки статуса / формата / сети --------------------------------------


@responses.activate
def test_unexpected_status_raises_api_error(client: SampleApisCoffeeClient) -> None:
    responses.add(
        responses.GET,
        BASE_URL,
        json={"message": "bad"},
        status=400,
        content_type="application/json",
    )

    with pytest.raises(CoffeeApiError):
        client.list_drinks()


@responses.activate
def test_html_instead_of_json_raises_api_error(
    client: SampleApisCoffeeClient,
) -> None:
    responses.add(
        responses.GET,
        f"{BASE_URL}/1",
        body="<html>Maintenance</html>",
        status=200,
        content_type="text/html",
    )

    with pytest.raises(CoffeeApiError):
        client.get_drink(1)


@responses.activate
def test_invalid_json_raises_api_error(client: SampleApisCoffeeClient) -> None:
    responses.add(
        responses.GET,
        f"{BASE_URL}/1",
        body="{broken",
        status=200,
        content_type="application/json",
    )

    with pytest.raises(CoffeeApiError):
        client.get_drink(1)


@responses.activate
def test_not_found_is_subclass_of_api_error(
    client: SampleApisCoffeeClient,
) -> None:
    responses.add(
        responses.GET,
        f"{BASE_URL}/1",
        json={},
        status=404,
        content_type="application/json",
    )

    with pytest.raises(CoffeeApiError) as exc_info:
        client.get_drink(1)

    assert isinstance(exc_info.value, CoffeeNotFoundError)


def test_network_error_raises_api_error(
    client: SampleApisCoffeeClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        raise requests.ConnectionError("offline")

    monkeypatch.setattr(requests, "request", boom)
    # На случай реализации через requests.get / .post и т.д.
    monkeypatch.setattr(requests, "get", boom)
    monkeypatch.setattr(requests, "post", boom)

    with pytest.raises(CoffeeApiError):
        client.list_drinks()


def test_timeout_error_raises_api_error(
    client: SampleApisCoffeeClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        raise requests.Timeout("slow")

    monkeypatch.setattr(requests, "request", boom)
    monkeypatch.setattr(requests, "get", boom)

    with pytest.raises(CoffeeApiError):
        client.list_drinks()


def test_request_uses_configured_timeout(
    client: SampleApisCoffeeClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_response() -> requests.Response:
        response = requests.Response()
        response.status_code = 200
        response._content = b"[]"
        response.headers["Content-Type"] = "application/json"
        response.url = BASE_URL
        return response

    def fake_request(*_args: object, **kwargs: object) -> requests.Response:
        captured.update(kwargs)
        return fake_response()

    def fake_get(*_args: object, **kwargs: object) -> requests.Response:
        captured.update(kwargs)
        return fake_response()

    monkeypatch.setattr(requests, "request", fake_request)
    monkeypatch.setattr(requests, "get", fake_get)

    client.list_drinks()
    assert captured.get("timeout") == client._timeout


@responses.activate
def test_status_checked_before_json_parse(
    client: SampleApisCoffeeClient,
) -> None:
    """При 500 с HTML клиент не должен падать с JSONDecodeError наружу."""
    responses.add(
        responses.GET,
        f"{BASE_URL}/1",
        body="<html>Error</html>",
        status=500,
        content_type="text/html",
    )

    with pytest.raises(CoffeeApiError):
        client.get_drink(1)


@responses.activate
def test_create_error_body_does_not_leak_raw_exception(
    client: SampleApisCoffeeClient,
    drink_payload: dict[str, object],
) -> None:
    responses.add(
        responses.POST,
        BASE_URL,
        json={
            "message": "The data you are sending does not match the existing data object.",
        },
        status=400,
        content_type="application/json",
    )

    with pytest.raises(CoffeeApiError):
        client.create_drink(drink_payload)
