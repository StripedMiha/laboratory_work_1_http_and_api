"""Тесты мока: python -m unittest discover -s mock_server -v (из корня воркшопа)."""

import http.client
import io
import json
import socket
import sys
import threading
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
import server  # noqa: E402

SEED = {
    "hot": [
        {"title": "Latte", "description": "Milk", "ingredients": ["Espresso", "Steamed milk"],
         "image": "https://img/latte", "id": 2},
        {"title": "Caramel Latte", "description": "Sweet", "ingredients": ["Espresso", "Caramel"],
         "image": "", "id": 3},
        {"title": "Black Tea", "description": "Tea", "ingredients": ["Black tea"],
         "image": "", "id": 13},
        {"title": "string", "description": "junk", "ingredients": "array",
         "image": "string", "id": "number"},
    ],
    "iced": [
        {"title": "Iced Coffee", "description": "Cold", "ingredients": ["Coffee", "Ice"],
         "image": "", "id": 1},
    ],
}
SHAPE = {"title": "string", "description": "string", "ingredients": "array",
         "image": "string", "id": "number"}
NEW = {"title": "Americano mock", "description": "Water", "ingredients": ["Espresso"], "image": ""}


class ServerTestCase(unittest.TestCase):
    faults: dict[str, str] = {}
    slow_seconds = 0.5

    def setUp(self) -> None:
        self.server = server.MockServer(
            ("127.0.0.1", 0), server.Store(SEED), dict(self.faults), self.slow_seconds, quiet=True
        )
        self.port = self.server.server_address[1]
        thread = threading.Thread(
            target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def request(self, method, path, body=None, *, raw=None, content_type="application/json",
                timeout=5.0):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=timeout)
        headers = {}
        if body is not None or raw is not None:
            data = raw if raw is not None else json.dumps(body).encode()
            headers["Content-Type"] = content_type
        else:
            data = None
        try:
            connection.request(method, path, body=data, headers=headers)
            response = connection.getresponse()
            payload = response.read()
            content = json.loads(payload) if payload and "json" in response.getheader(
                "Content-Type", "") else payload
            return response.status, dict(response.getheaders()), content
        finally:
            connection.close()


class ReadTests(ServerTestCase):
    def test_list(self):
        status, headers, data = self.request("GET", "/coffee/hot")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "application/json; charset=utf-8")
        self.assertEqual(headers["X-Total-Count"], "4")
        self.assertEqual([item["id"] for item in data], [2, 3, 13, "number"])

    def test_list_trailing_slash_and_other_collection(self):
        self.assertEqual(self.request("GET", "/coffee/hot/")[0], 200)
        status, _, data = self.request("GET", "/coffee/iced/1")
        self.assertEqual((status, data["title"]), (200, "Iced Coffee"))

    def test_get_item(self):
        status, _, data = self.request("GET", "/coffee/hot/2")
        self.assertEqual(status, 200)
        self.assertEqual(data, SEED["hot"][0])

    def test_get_item_ignores_query(self):
        self.assertEqual(self.request("GET", "/coffee/hot/2?title=zzz")[0], 200)

    def test_missing_item_is_404_with_empty_json(self):
        for path in ("/coffee/hot/999", "/coffee/hot/abc", "/coffee/hot/02"):
            status, headers, data = self.request("GET", path)
            self.assertEqual((status, data), (404, {}), path)
            self.assertTrue(headers["Content-Type"].startswith("application/json"))

    def test_string_id_is_matched_as_string(self):
        status, _, data = self.request("GET", "/coffee/hot/number")
        self.assertEqual((status, data["title"]), (200, "string"))

    def test_unknown_collection_and_routes(self):
        self.assertEqual(self.request("GET", "/coffee/nothing")[::2], (404, {}))
        status, _, data = self.request("GET", "/coffee")
        self.assertEqual((status, data), (404, {"error": 404, "message": "Cannot GET /coffee"}))
        status, _, data = self.request("POST", "/coffee/hot/2", NEW)
        self.assertEqual((status, data["message"]), (404, "Cannot POST /coffee/hot/2"))
        status, _, data = self.request("DELETE", "/coffee/hot")
        self.assertEqual((status, data["message"]), (404, "Cannot DELETE /coffee/hot"))

    def test_head(self):
        status, headers, data = self.request("HEAD", "/coffee/hot")
        self.assertEqual((status, data), (200, b""))
        self.assertEqual(headers["X-Total-Count"], "4")


class QueryTests(ServerTestCase):
    def ids(self, query):
        status, headers, data = self.request("GET", "/coffee/hot?" + query)
        self.assertEqual(status, 200)
        return [item["id"] for item in data], headers

    def test_exact_filter_is_case_sensitive(self):
        self.assertEqual(self.ids("title=Latte")[0], [2])
        self.assertEqual(self.ids("title=latte")[0], [])
        self.assertEqual(self.ids("id=2")[0], [2])
        self.assertEqual(self.ids("search=Latte")[0], [])

    def test_like_ne_and_full_text(self):
        self.assertEqual(self.ids("title_like=latte")[0], [2, 3])
        self.assertEqual(self.ids("title_ne=Latte")[0], [3, 13, "number"])
        self.assertEqual(self.ids("q=caramel")[0], [3])

    def test_sort(self):
        self.assertEqual(self.ids("_sort=title")[0], [13, 3, 2, "number"])
        self.assertEqual(self.ids("_sort=title&_order=desc")[0], ["number", 2, 3, 13])

    def test_limit_keeps_total(self):
        ids, headers = self.ids("_limit=2")
        self.assertEqual((ids, headers["X-Total-Count"]), ([2, 3], "4"))
        self.assertEqual(self.ids("_start=1&_end=3")[0], [3, 13])

    def test_page_and_link_header(self):
        ids, headers = self.ids("_page=2&_limit=1")
        self.assertEqual(ids, [3])
        link = headers["Link"]
        for rel, page in (("first", 1), ("prev", 1), ("next", 3), ("last", 4)):
            self.assertIn(f'_page={page}&_limit=1>; rel="{rel}"', link)

    def test_bad_regex_is_400(self):
        status, _, data = self.request("GET", "/coffee/hot?title_like=%5B")
        self.assertEqual((status, data["error"]), (400, 400))


class CreateTests(ServerTestCase):
    def test_create(self):
        status, headers, data = self.request("POST", "/coffee/hot", NEW)
        self.assertEqual(status, 201)
        self.assertEqual(data, {**NEW, "id": 14})
        self.assertEqual(headers["Location"], "/coffee/hot/14")
        self.assertEqual(self.request("GET", "/coffee/hot/14")[2], data)

    def test_missing_fields(self):
        for body in ({"title": "x"}, {}, {k: v for k, v in NEW.items() if k != "image"}, [1]):
            status, _, data = self.request("POST", "/coffee/hot", body)
            self.assertEqual(status, 400, body)
            self.assertEqual(data["message"], server.SHAPE_MISMATCH)
            self.assertEqual(data["expected"], SHAPE)
            self.assertEqual(data["received"], body)

    def test_types_and_extra_fields_not_checked(self):
        body = {"title": 5, "description": "", "ingredients": "E", "image": "", "price": 3}
        status, _, data = self.request("POST", "/coffee/hot", body)
        self.assertEqual((status, data), (201, {**body, "id": 14}))

    def test_invalid_json(self):
        status, _, data = self.request("POST", "/coffee/hot", raw=b"{bad")
        self.assertEqual((status, data), (400, {"error": 400, "message": server.SOMETHING_WRONG}))

    def test_form_encoded_body_is_not_json(self):
        raw = json.dumps(NEW).encode()
        status, _, data = self.request(
            "POST", "/coffee/hot", raw=raw, content_type="application/x-www-form-urlencoded")
        self.assertEqual(status, 400)
        self.assertEqual(data["received"], {raw.decode(): ""})

    def test_client_id_is_used_and_duplicate_rejected(self):
        status, headers, data = self.request("POST", "/coffee/hot", {**NEW, "id": 500})
        self.assertEqual((status, data["id"], headers["Location"]), (201, 500, "/coffee/hot/500"))
        self.assertEqual(self.request("POST", "/coffee/hot", NEW)[2]["id"], 501)

    def test_duplicate_id_is_400_with_description(self):
        # Занятость id проверяется по строковому виду, как и поиск записи.
        for taken in (2, "2", "number"):
            body = {**NEW, "id": taken}
            status, headers, data = self.request("POST", "/coffee/hot", body)
            self.assertEqual(status, 400, taken)
            self.assertNotIn("Location", headers)
            self.assertEqual(data, {
                "error": 400,
                "message": server.DUPLICATE_ID.format(id=taken),
                "received": body,
            })
        self.assertEqual(self.request("GET", "/coffee/hot")[1]["X-Total-Count"], "4")
        self.assertEqual(self.request("GET", "/coffee/hot/2")[2], SEED["hot"][0])

    def test_id_is_reused_after_delete(self):
        first = self.request("POST", "/coffee/hot", NEW)[2]["id"]
        self.assertEqual(self.request("DELETE", f"/coffee/hot/{first}")[0], 200)
        self.assertEqual(self.request("POST", "/coffee/hot", NEW)[2]["id"], first)


class ChangeTests(ServerTestCase):
    def test_put_replaces_and_takes_id_from_url(self):
        old = {**SEED["hot"][1], "price": 1}
        self.request("PUT", "/coffee/hot/3", {k: v for k, v in old.items() if k != "id"})
        body = {**NEW, "id": 999}
        status, _, data = self.request("PUT", "/coffee/hot/3", body)
        self.assertEqual((status, data), (200, {**NEW, "id": 3}))
        self.assertNotIn("price", self.request("GET", "/coffee/hot/3")[2])
        self.assertEqual(self.request("GET", "/coffee/hot/999")[0], 404)

    def test_put_partial_is_400_even_for_missing_id(self):
        for path in ("/coffee/hot/3", "/coffee/hot/999"):
            status, _, data = self.request("PUT", path, {"title": "x"})
            self.assertEqual((status, data["message"]), (400, server.SHAPE_MISMATCH))

    def test_put_missing_is_404(self):
        self.assertEqual(self.request("PUT", "/coffee/hot/999", NEW)[::2], (404, {}))

    def test_patch_changes_only_given_fields(self):
        status, _, data = self.request("PATCH", "/coffee/hot/2", {"description": "New", "id": 7})
        self.assertEqual((status, data), (200, {**SEED["hot"][0], "description": "New"}))
        self.assertEqual(self.request("GET", "/coffee/hot/2")[2]["description"], "New")

    def test_patch_does_not_check_types(self):
        status, _, data = self.request("PATCH", "/coffee/hot/2", {"ingredients": "x"})
        self.assertEqual((status, data["ingredients"]), (200, "x"))

    def test_patch_unknown_or_empty_is_400(self):
        for body in ({"price": 3}, {}, [1]):
            status, _, data = self.request("PATCH", "/coffee/hot/2", body)
            self.assertEqual((status, data["message"]), (400, server.UNKNOWN_FIELDS), body)

    def test_patch_missing_is_404(self):
        self.assertEqual(self.request("PATCH", "/coffee/hot/999", {"title": "x"})[0], 404)

    def test_delete(self):
        status, headers, data = self.request("DELETE", "/coffee/hot/2")
        self.assertEqual((status, data), (200, {}))
        self.assertTrue(headers["Content-Type"].startswith("application/json"))
        self.assertEqual(self.request("GET", "/coffee/hot/2")[0], 404)
        self.assertEqual(self.request("DELETE", "/coffee/hot/2")[0], 404)

    def test_servers_do_not_share_state(self):
        self.request("DELETE", "/coffee/hot/2")
        self.assertEqual(SEED["hot"][0]["id"], 2)


class HtmlFaultTests(ServerTestCase):
    faults = {"GET": "html", "PUT": "500", "PATCH": "502"}

    def test_faults(self):
        status, headers, body = self.request("GET", "/coffee/hot")
        self.assertEqual(status, 200)
        self.assertTrue(headers["Content-Type"].startswith("text/html"))
        self.assertIn(b"<html>", body)
        self.assertEqual(self.request("PUT", "/coffee/hot/2", NEW)[0], 500)
        status, headers, _ = self.request("PATCH", "/coffee/hot/2", {"title": "x"})
        self.assertEqual((status, headers["Content-Type"][:9]), (502, "text/html"))
        self.assertEqual(self.request("POST", "/coffee/hot", NEW)[0], 201)


class SlowAndDropFaultTests(ServerTestCase):
    faults = {"POST": "slow", "DELETE": "drop"}
    slow_seconds = 0.5

    def test_slow_post_still_creates(self):
        with self.assertRaises(socket.timeout):
            self.request("POST", "/coffee/hot", NEW, timeout=0.1)
        for _ in range(50):
            if self.request("GET", "/coffee/hot?title=Americano%20mock")[2]:
                break
            threading.Event().wait(0.05)
        self.assertEqual(self.request("GET", "/coffee/hot/14")[0], 200)

    def test_drop(self):
        with self.assertRaises((http.client.RemoteDisconnected, ConnectionError)):
            self.request("DELETE", "/coffee/hot/2")
        self.assertEqual(self.request("GET", "/coffee/hot/2")[0], 200)


class FaultArgumentTests(unittest.TestCase):
    def test_parse_fault(self):
        self.assertEqual(server.parse_fault("post=SLOW"), ("POST", "slow"))
        self.assertEqual(server.parse_fault("*=500"), ("*", "500"))
        for bad in ("POST", "POST=boom", "=html"):
            with self.assertRaises(Exception):
                server.parse_fault(bad)


class ReferenceSolutionTests(ServerTestCase):
    """Эталонный solution.py проходит весь сценарий на моке."""

    def test_solution_scenario(self):
        root = Path(__file__).resolve().parent.parent
        if not (root / "solution.py").exists():
            self.skipTest("solution.py не найден")
        try:
            import requests  # noqa: F401
        except ImportError:
            self.skipTest("нужен пакет requests")
        sys.path.insert(0, str(root))
        import solution

        base_url = f"http://127.0.0.1:{self.port}/coffee/hot"
        original = solution.SampleApisCoffeeClient
        output = io.StringIO()
        with mock.patch.object(solution, "SampleApisCoffeeClient",
                               lambda: original(base_url=base_url, timeout=5)):
            with redirect_stdout(output):
                code = solution.main()
        self.assertEqual(code, 0, output.getvalue())
        self.assertIn("Сценарий выполнен успешно.", output.getvalue())
        self.assertEqual(self.request("GET", "/coffee/hot")[1]["X-Total-Count"], "4")


if __name__ == "__main__":
    unittest.main()
