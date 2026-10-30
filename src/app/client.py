"""
Описание запроса создания горячего кофе
---------------------------------------
Заполните этот docstring после исследования API.

Укажите:
- HTTP-метод и URL;
- необходимые заголовки;
- параметры JSON-тела (тип, обязательность, ограничения);
- какие поля задаёт клиент, а какие создаёт сервер;
- ожидаемый успешный статус и форму ответа;
- какие правила подтверждены запросами к API, а какие проверяете только в клиенте.

Формальная OpenAPI / JSON Schema не требуется.
"""

import requests

JsonObject = dict[str, object]


class SampleApisCoffeeClient:
    def __init__(
        self,
        base_url: str = "https://api.sampleapis.com/coffee/hot",
        timeout: float = 10.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def list_drinks(self) -> list[JsonObject]:
        raise NotImplementedError

    def get_drink(self, drink_id: int) -> JsonObject:
        raise NotImplementedError

    def create_drink(self, payload: JsonObject) -> JsonObject:
        raise NotImplementedError

    def replace_drink(
        self,
        drink_id: int,
        payload: JsonObject,
    ) -> JsonObject:
        raise NotImplementedError

    def update_drink(
        self,
        drink_id: int,
        changes: JsonObject,
    ) -> JsonObject:
        raise NotImplementedError

    def delete_drink(self, drink_id: int) -> None:
        raise NotImplementedError

    def _request(
        self,
        method: str,
        path: str = "",
        payload: JsonObject | None = None,
    ) -> requests.Response:
        raise NotImplementedError
