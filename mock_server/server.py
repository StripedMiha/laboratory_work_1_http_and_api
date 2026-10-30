"""Локальный мок SampleAPIs Coffee (https://api.sampleapis.com/coffee).

Повторяет поведение публичного API, установленное пробными запросами
5 октября 2026 года: маршруты, статусы, тела ошибок, заголовки, правила
проверки тела и выдачи id. Данные хранятся в памяти и сбрасываются при
перезапуске; начальное состояние берётся из data.json (снимок реального API).

Запуск (нужен только Python 3.10+, сторонние пакеты не используются):

    python mock_server/server.py                    # http://127.0.0.1:8000
    python mock_server/server.py --port 9000
    python mock_server/server.py --fault POST=slow  # POST отвечает с задержкой

Базовый URL для клиента: http://127.0.0.1:8000/coffee/hot
Подробности — в README.md рядом.
"""

import argparse
import copy
import json
import re
import sys
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlencode, urlsplit

PREFIX = "coffee"
DEFAULT_DATA = Path(__file__).with_name("data.json")

SHAPE_MISMATCH = (
    "The data you are sending does not match the existing data object. "
    "Check out the expected shape versus what was sent."
)
UNKNOWN_FIELDS = (
    "It appears you are trying to manipulate data that does not exist on the "
    "object. Check out the expected shape versus what was sent."
)
SOMETHING_WRONG = "Something went wrong handling that request."
DUPLICATE_ID = (
    "A record with id {id!r} already exists. "
    "Omit id from the request body to let the server assign one."
)

FAULT_KINDS = ("slow", "html", "500", "502", "drop")


class BadRequest(Exception):
    """Тело запроса или параметры не удалось разобрать."""


class DuplicateIdError(Exception):
    pass


def type_name(value: object) -> str:
    """Имя типа в формате поля "expected" из ответов API."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    return "object"


def is_int_id(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


class Store:
    """Коллекции в памяти. Все операции выполняются под одной блокировкой."""

    def __init__(self, collections: dict[str, list[dict]]) -> None:
        self._collections = copy.deepcopy(collections)
        self._lock = threading.Lock()
        # «Ожидаемая форма» объекта: имена полей и типы первой записи,
        # как в поле "expected" ответов 400 реального API.
        self._shapes = {
            name: {key: type_name(value) for key, value in items[0].items()}
            for name, items in self._collections.items()
            if items
        }

    def has(self, collection: str) -> bool:
        return collection in self._collections

    def shape(self, collection: str) -> dict[str, str]:
        return self._shapes.get(collection, {})

    def list(self, collection: str) -> list[dict]:
        with self._lock:
            return copy.deepcopy(self._collections[collection])

    def get(self, collection: str, raw_id: str) -> dict | None:
        with self._lock:
            index = self._find(collection, raw_id)
            if index is None:
                return None
            return copy.deepcopy(self._collections[collection][index])

    def insert(self, collection: str, body: dict) -> dict:
        with self._lock:
            items = self._collections[collection]
            if body.get("id") is None:
                # Новый id — «максимальный целый + 1»; строковые id не учитываются.
                # Поэтому id удалённой последней записи выдаётся повторно.
                int_ids = [item["id"] for item in items if is_int_id(item.get("id"))]
                item = {**body, "id": max(int_ids, default=0) + 1}
            else:
                if self._find(collection, str(body["id"])) is not None:
                    raise DuplicateIdError(body["id"])
                item = dict(body)
            items.append(item)
            return copy.deepcopy(item)

    def replace(self, collection: str, raw_id: str, body: dict) -> dict | None:
        with self._lock:
            index = self._find(collection, raw_id)
            if index is None:
                return None
            items = self._collections[collection]
            fields = {key: value for key, value in body.items() if key != "id"}
            items[index] = {**fields, "id": items[index]["id"]}
            return copy.deepcopy(items[index])

    def update(self, collection: str, raw_id: str, changes: dict) -> dict | None:
        with self._lock:
            index = self._find(collection, raw_id)
            if index is None:
                return None
            item = self._collections[collection][index]
            item.update({key: value for key, value in changes.items() if key != "id"})
            return copy.deepcopy(item)

    def delete(self, collection: str, raw_id: str) -> bool:
        with self._lock:
            index = self._find(collection, raw_id)
            if index is None:
                return False
            del self._collections[collection][index]
            return True

    def _find(self, collection: str, raw_id: str) -> int | None:
        # Как в json-server: id из URL сравнивается со строковым видом id
        # записи, поэтому /hot/number находит запись с id="number",
        # а /hot/02 не находит запись с id=2.
        for index, item in enumerate(self._collections[collection]):
            if str(item.get("id")) == raw_id:
                return index
        return None


# ---------------------------------------------------------------- запросы ---


def query_list(items: list[dict], params: dict[str, list[str]]) -> tuple[list[dict], dict]:
    """Фильтры, поиск, сортировка и пагинация в духе json-server.

    Возвращает отобранные записи и сведения для заголовков: общее число
    записей после фильтрации и параметры пагинации.
    """
    result = items
    for key, values in params.items():
        if key == "q" or key.startswith("_"):
            continue
        if key.endswith("_like"):
            field = key[: -len("_like")]
            patterns = [re.compile(value, re.IGNORECASE) for value in values]
            result = [
                item for item in result
                if field in item and any(p.search(str(item[field])) for p in patterns)
            ]
        elif key.endswith("_ne"):
            field = key[: -len("_ne")]
            result = [item for item in result if str(item.get(field)) not in values]
        else:
            result = [
                item for item in result
                if key in item and json_text(item[key]) in values
            ]

    if "q" in params:
        needle = params["q"][-1].lower()
        result = [item for item in result if needle in all_strings(item).lower()]

    if "_sort" in params:
        fields = params["_sort"][-1].split(",")
        orders = params.get("_order", ["asc"])[-1].split(",")
        # Устойчивая сортировка: проходим поля с последнего к первому.
        for position in reversed(range(len(fields))):
            order = orders[position] if position < len(orders) else "asc"
            result = sorted(
                result,
                key=lambda item, f=fields[position]: sort_key(item.get(f)),
                reverse=order.lower() == "desc",
            )

    total = len(result)
    paging: dict = {}
    if "_page" in params:
        page = max(int(params["_page"][-1]), 1)
        limit = int(params.get("_limit", ["10"])[-1])
        paging = {"page": page, "limit": limit, "last": max((total + limit - 1) // limit, 1)}
        result = result[(page - 1) * limit : page * limit]
    elif "_start" in params or "_end" in params or "_limit" in params:
        start = int(params.get("_start", ["0"])[-1])
        if "_end" in params:
            end = int(params["_end"][-1])
        elif "_limit" in params:
            end = start + int(params["_limit"][-1])
        else:
            end = None
        result = result[start:end]
    return result, {"total": total, "paging": paging}


def json_text(value: object) -> str:
    """Строковое представление значения для точного фильтра поле=значение."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (str, int, float)):
        return str(value)
    return json.dumps(value, ensure_ascii=False)


def all_strings(value: object) -> str:
    """Все строковые и числовые значения записи — для полнотекстового q."""
    if isinstance(value, dict):
        return " ".join(all_strings(v) for v in value.values())
    if isinstance(value, list):
        return " ".join(all_strings(v) for v in value)
    return "" if value is None else str(value)


def sort_key(value: object) -> tuple:
    # Значения разных типов не сравниваются в Python напрямую:
    # сначала числа, затем строки, затем всё остальное.
    if is_int_id(value) or isinstance(value, float):
        return (0, value, "")
    if isinstance(value, str):
        return (1, 0, value)
    return (2, 0, json.dumps(value, ensure_ascii=False))


# ------------------------------------------------------------------ HTTP ---


class MockServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        address: tuple[str, int],
        store: Store,
        faults: dict[str, str] | None = None,
        slow_seconds: float = 30.0,
        quiet: bool = False,
    ) -> None:
        super().__init__(address, ApiHandler)
        self.store = store
        self.faults = faults or {}
        self.slow_seconds = slow_seconds
        self.quiet = quiet

    def handle_error(self, request, client_address) -> None:
        # Клиент не дождался ответа (тайм-аут, сбой slow) — это не ошибка мока.
        if isinstance(sys.exc_info()[1], ConnectionError):
            return
        super().handle_error(request, client_address)


class ApiHandler(BaseHTTPRequestHandler):
    server: MockServer
    server_version = "SampleApisMock/1.0"

    # ---- точки входа ----

    def do_GET(self) -> None:
        self._dispatch("GET")

    def do_HEAD(self) -> None:
        self._dispatch("HEAD")

    def do_POST(self) -> None:
        self._dispatch("POST")

    def do_PUT(self) -> None:
        self._dispatch("PUT")

    def do_PATCH(self) -> None:
        self._dispatch("PATCH")

    def do_DELETE(self) -> None:
        self._dispatch("DELETE")

    def do_OPTIONS(self) -> None:
        # Реальный API на OPTIONS не отвечает (зависает); для мока достаточно
        # обычного ответа на CORS preflight.
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,HEAD,PUT,PATCH,POST,DELETE")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", "0")
        self.end_headers()

    # ---- маршрутизация ----

    def _dispatch(self, method: str) -> None:
        url = urlsplit(self.path)
        body_bytes = self._read_body()

        fault = self.server.faults.get(method) or self.server.faults.get("*")
        if fault == "slow":
            time.sleep(self.server.slow_seconds)
        elif fault is not None:
            self._send_fault(fault)
            return

        parts = [part for part in url.path.split("/") if part]
        try:
            if len(parts) == 2 and parts[0] == PREFIX and method in ("GET", "HEAD", "POST"):
                self._collection(method, parts[1], url.query, body_bytes)
            elif len(parts) == 3 and parts[0] == PREFIX and method != "POST":
                self._item(method, parts[1], parts[2], body_bytes)
            else:
                self._send_json(404, {"error": 404, "message": f"Cannot {method} {url.path}"})
        except BadRequest:
            self._send_json(400, {"error": 400, "message": SOMETHING_WRONG})

    def _collection(self, method: str, name: str, query: str, body_bytes: bytes) -> None:
        store = self.server.store
        if not store.has(name):
            self._send_json(404, {})
            return

        if method in ("GET", "HEAD"):
            params = parse_qs(query, keep_blank_values=True)
            try:
                items, info = query_list(store.list(name), params)
            except (re.error, ValueError) as error:
                raise BadRequest from error
            headers = {"X-Total-Count": str(info["total"])}
            if info["paging"]:
                headers["Link"] = self._link_header(name, params, info["paging"])
            self._send_json(200, items, headers)
            return

        body = self._parse_body(body_bytes)
        if not self._has_all_fields(name, body):
            self._send_shape_error(name, SHAPE_MISMATCH, body)
            return
        try:
            item = store.insert(name, body)
        except DuplicateIdError:
            self._send_json(400, {
                "error": 400,
                "message": DUPLICATE_ID.format(id=body["id"]),
                "received": body,
            })
            return
        location = f"/{PREFIX}/{name}/{quote(str(item['id']))}"
        self._send_json(201, item, {"Location": location})

    def _item(self, method: str, name: str, raw_id: str, body_bytes: bytes) -> None:
        store = self.server.store
        if not store.has(name):
            self._send_json(404, {})
            return

        if method in ("GET", "HEAD"):
            item = store.get(name, raw_id)
        elif method == "DELETE":
            item = {} if store.delete(name, raw_id) else None
        elif method == "PUT":
            # Сначала проверяется форма тела, потом существование записи:
            # PUT неполного тела на отсутствующий id даёт 400, а не 404.
            body = self._parse_body(body_bytes)
            if not self._has_all_fields(name, body):
                self._send_shape_error(name, SHAPE_MISMATCH, body)
                return
            item = store.replace(name, raw_id, body)
        else:  # PATCH
            body = self._parse_body(body_bytes)
            shape = store.shape(name)
            if not isinstance(body, dict) or not body or not set(body) <= set(shape):
                self._send_shape_error(name, UNKNOWN_FIELDS, body)
                return
            item = store.update(name, raw_id, body)

        if item is None:
            self._send_json(404, {})
        else:
            self._send_json(200, item)

    # ---- тело запроса ----

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length) if length > 0 else b""

    def _parse_body(self, raw: bytes) -> object:
        """Разбирает тело так же, как express.json() и express.urlencoded().

        Без Content-Type: application/json тело JSON не разбирается: при
        urlencoded вся строка становится ключом с пустым значением, при
        прочих типах тело считается пустым объектом.
        """
        media_type = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if media_type == "application/json" or media_type.endswith("+json"):
            if not raw.strip():
                return {}
            try:
                return json.loads(raw)
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise BadRequest from error
        if media_type == "application/x-www-form-urlencoded":
            parsed = parse_qs(raw.decode("utf-8", "replace"), keep_blank_values=True)
            return {key: values[0] if len(values) == 1 else values for key, values in parsed.items()}
        return {}

    def _has_all_fields(self, name: str, body: object) -> bool:
        # Сервер проверяет только наличие полей, но не их типы и значения;
        # id в теле не обязателен, лишние поля допускаются.
        required = [field for field in self.server.store.shape(name) if field != "id"]
        return isinstance(body, dict) and all(field in body for field in required)

    # ---- ответы ----

    def _send_shape_error(self, name: str, message: str, received: object) -> None:
        self._send_json(400, {
            "error": 400,
            "message": message,
            "expected": self.server.store.shape(name),
            "received": received,
        })

    def _send_json(self, status: int, data: object, headers: dict[str, str] | None = None) -> None:
        body = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Expose-Headers", "X-Total-Count,Link,Location")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _send_fault(self, kind: str) -> None:
        if kind == "drop":
            # Закрываем соединение без ответа — клиент получит ConnectionError.
            self.close_connection = True
            self.connection.close()
            return
        if kind == "500":
            self._send_json(500, {"error": 500, "message": "Internal Server Error"})
            return
        status = 200 if kind == "html" else 502
        body = (
            "<!DOCTYPE html><html><head><title>Coffee</title></head>"
            f"<body><h1>{'Welcome' if status == 200 else '502 Bad Gateway'}</h1></body></html>"
        ).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _link_header(self, name: str, params: dict[str, list[str]], paging: dict) -> str:
        host = self.headers.get("Host") or "{}:{}".format(*self.server.server_address[:2])
        base = f"http://{host}/{PREFIX}/{name}"

        def link(page: int, rel: str) -> str:
            query = {key: values[-1] for key, values in params.items()}
            query.update({"_page": str(page), "_limit": str(paging["limit"])})
            return f'<{base}?{urlencode(query)}>; rel="{rel}"'

        page, last = paging["page"], paging["last"]
        links = [link(1, "first")]
        if page > 1:
            links.append(link(page - 1, "prev"))
        if page < last:
            links.append(link(page + 1, "next"))
        links.append(link(last, "last"))
        return ", ".join(links)

    def log_message(self, format: str, *args: object) -> None:
        if not self.server.quiet:
            sys.stderr.write(f"[mock] {self.address_string()} {format % args}\n")


# ------------------------------------------------------------------ запуск ---


def parse_fault(spec: str) -> tuple[str, str]:
    method, sep, kind = spec.partition("=")
    method = method.strip().upper()
    kind = kind.strip().lower()
    if not sep or not method or kind not in FAULT_KINDS:
        raise argparse.ArgumentTypeError(
            f"ожидается МЕТОД=ВИД, где ВИД — один из {', '.join(FAULT_KINDS)}; "
            f"МЕТОД — GET, POST, ... или *"
        )
    return method, kind


def load_data(path: Path) -> dict[str, list[dict]]:
    with path.open(encoding="utf-8") as file:
        data = json.load(file)
    if not isinstance(data, dict) or not all(isinstance(v, list) for v in data.values()):
        raise ValueError(f"{path}: ожидается объект {{\"коллекция\": [записи]}}")
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Мок SampleAPIs Coffee")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA,
                        help="JSON с начальными данными (по умолчанию data.json)")
    parser.add_argument("--fault", type=parse_fault, action="append", default=[],
                        metavar="МЕТОД=ВИД",
                        help="сбой для метода: slow (задержка, затем обычная обработка), "
                             "html (200 text/html), 500, 502 (HTML), drop (разрыв "
                             "соединения). Можно указать несколько раз; * — все методы")
    parser.add_argument("--slow-seconds", type=float, default=30.0,
                        help="задержка для сбоя slow, секунд (по умолчанию 30)")
    parser.add_argument("--quiet", action="store_true", help="не печатать журнал запросов")
    args = parser.parse_args(argv)

    store = Store(load_data(args.data))
    server = MockServer((args.host, args.port), store, dict(args.fault),
                        args.slow_seconds, args.quiet)
    host, port = server.server_address[:2]
    print(f"Мок SampleAPIs Coffee: http://{host}:{port}/{PREFIX}/hot", file=sys.stderr)
    for method, kind in args.fault:
        print(f"  сбой: {method} -> {kind}", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
