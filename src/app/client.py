"""
Описание запроса создания горячего кофе
---------------------------------------

Запрос
    POST https://api.sampleapis.com/coffee/hot

Заголовки
    Content-Type: application/json (обязателен). Без него сервер не
    разбирает тело как JSON и отвечает 400. Клиент задаёт его сам: библиотека
    requests ставит этот заголовок, когда тело передано через параметр json=.

Тело запроса (JSON-объект), все четыре поля обязательны:
    title        строка   название напитка;
    description  строка   описание;
    ingredients  список   ингредиенты, список строк;
    image        строка   ссылка на картинку (может быть пустой строкой).
Поле id в теле не передаём.

Кто что задаёт
    Клиент задаёт title, description, ingredients, image.
    Сервер создаёт id: берёт максимальный числовой id в коллекции и
    прибавляет 1 (id удалённой последней записи может выдаться повторно).

Успешный ответ
    Статус 201, Content-Type: application/json, в теле объект напитка со
    всеми отправленными полями и новым id. Заголовок Location содержит адрес
    новой записи. Клиент берёт id из тела ответа.

Что подтверждено запросами к API (по описанию mock_server, который сверён
с реальным API)
    - без любого из четырёх полей сервер отвечает 400 и показывает
      ожидаемую форму объекта (expected) и то, что получил (received);
    - типы значений сервер не проверяет: title=5 или пустые строки он
      принимает;
    - лишние поля сервер сохраняет;
    - без заголовка Content-Type: application/json ответ 400.

Что проверяет только клиент (локальная проверка перед отправкой)
    - все четыре поля на месте;
    - title - непустая строка;
    - ingredients - непустой список из строк.
    Эти ограничения выбраны нами для порядка, сервер их не требует.

Повторять POST после тайм-аута нельзя: сервер мог создать запись, а ответ
не дошёл. Такую запись ищут вручную по метке в названии.
"""

import requests

from app.exceptions import CoffeeApiError, CoffeeNotFoundError

JsonObject = dict[str, object]

REQUIRED_FIELDS = ("title", "description", "ingredients", "image")


class SampleApisCoffeeClient:
    def __init__(
        self,
        base_url: str = "https://api.sampleapis.com/coffee/hot",
        timeout: float = 10.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def list_drinks(self) -> list[JsonObject]:
        response = self._request("GET")
        data = self._read_json(response)
        if not isinstance(data, list):
            raise CoffeeApiError("Ожидался список напитков, пришёл другой JSON")
        return data

    def get_drink(self, drink_id: int) -> JsonObject:
        response = self._request("GET", f"/{drink_id}")
        return self._read_object(response)

    def create_drink(self, payload: JsonObject) -> JsonObject:
        self._check_payload(payload)
        response = self._request("POST", payload=payload)
        drink = self._read_object(response)
        if "id" not in drink:
            raise CoffeeApiError("В ответе на создание нет поля id")
        return drink

    def replace_drink(
        self,
        drink_id: int,
        payload: JsonObject,
    ) -> JsonObject:
        self._check_payload(payload)
        response = self._request("PUT", f"/{drink_id}", payload)
        return self._read_object(response)

    def update_drink(
        self,
        drink_id: int,
        changes: JsonObject,
    ) -> JsonObject:
        response = self._request("PATCH", f"/{drink_id}", changes)
        return self._read_object(response)

    def delete_drink(self, drink_id: int) -> None:
        # The body of a successful DELETE is not used, so it is not parsed.
        self._request("DELETE", f"/{drink_id}")

    def _request(
        self,
        method: str,
        path: str = "",
        payload: JsonObject | None = None,
    ) -> requests.Response:
        """Send one request and check the status. The only place with HTTP."""
        url = f"{self._base_url}{path}"
        try:
            response = requests.request(
                method,
                url,
                json=payload,
                timeout=self._timeout,
            )
        except requests.RequestException as error:
            # Timeout, ConnectionError and other network problems.
            raise CoffeeApiError(f"{method} {url}: {error}") from error

        # The status is checked before the body is used.
        if response.status_code == 404:
            raise CoffeeNotFoundError(f"{method} {url}: ресурс не найден")
        if not 200 <= response.status_code < 300:
            raise CoffeeApiError(
                f"{method} {url}: неожиданный статус {response.status_code}"
            )
        return response

    def _read_json(self, response: requests.Response) -> object:
        """Return the parsed JSON, or raise if the body is not JSON."""
        content_type = response.headers.get("Content-Type", "")
        if "application/json" not in content_type:
            raise CoffeeApiError(f"Ожидался JSON, пришёл {content_type or 'ответ'}")
        try:
            return response.json()
        except ValueError as error:
            raise CoffeeApiError("Ответ содержит некорректный JSON") from error

    def _read_object(self, response: requests.Response) -> JsonObject:
        data = self._read_json(response)
        if not isinstance(data, dict):
            raise CoffeeApiError("Ожидался JSON-объект, пришёл другой JSON")
        return data

    def _check_payload(self, payload: JsonObject) -> None:
        """Local checks before sending POST or PUT (the server is looser)."""
        missing = [field for field in REQUIRED_FIELDS if field not in payload]
        if missing:
            raise ValueError(f"Не хватает полей: {', '.join(missing)}")

        title = payload["title"]
        if not isinstance(title, str) or not title.strip():
            raise ValueError("title должен быть непустой строкой")

        ingredients = payload["ingredients"]
        if (
            not isinstance(ingredients, list)
            or not ingredients
            or not all(isinstance(item, str) for item in ingredients)
        ):
            raise ValueError("ingredients должен быть непустым списком строк")
