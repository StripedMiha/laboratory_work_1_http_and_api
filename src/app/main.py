from uuid import uuid4

from app.client import JsonObject, SampleApisCoffeeClient
from app.exceptions import CoffeeApiError, CoffeeNotFoundError


def check_fields(actual: JsonObject, expected: JsonObject, stage: str) -> None:
    """Raise ValueError if any expected field differs in the actual drink."""
    for field, value in expected.items():
        if actual.get(field) != value:
            raise ValueError(
                f"{stage}: поле {field} = {actual.get(field)!r}, "
                f"ожидалось {value!r}"
            )


def main() -> int:
    client = SampleApisCoffeeClient()
    marker = uuid4().hex[:8]
    created_id = None
    post_sent = False
    try:
        # 1. GET the collection.
        drinks = client.list_drinks()
        print(f"1. GET список: получено напитков - {len(drinks)}")

        # 2. POST a new drink; the marker makes the title unique for our group.
        new_drink = {
            "title": f"Group coffee {marker}",
            "description": "Drink created by the workshop script",
            "ingredients": ["Water", "Coffee"],
            "image": "https://example.com/coffee.jpg",
        }
        post_sent = True
        created = client.create_drink(new_drink)
        # 3. Save the id right away, so the drink can be deleted later.
        created_id = created["id"]
        print(f"2. POST: создан напиток id={created_id}, метка {marker}")

        # 4. GET by id and compare with what was sent.
        fetched = client.get_drink(created_id)
        check_fields(fetched, new_drink, "GET после POST")
        print("3. GET по id: все поля совпадают с отправленными")

        # 5. PUT replaces every field, then GET to check.
        replacement = {
            "title": f"Group coffee {marker} (replaced)",
            "description": "Fully replaced drink",
            "ingredients": ["Espresso"],
            "image": "https://example.com/replaced.jpg",
        }
        client.replace_drink(created_id, replacement)
        fetched = client.get_drink(created_id)
        check_fields(fetched, replacement, "GET после PUT")
        print("4. PUT + GET: все поля заменены")

        # 6. PATCH changes one field, the others must stay the same.
        changes = {"description": "Changed only by PATCH"}
        client.update_drink(created_id, changes)
        fetched = client.get_drink(created_id)
        check_fields(fetched, changes, "GET после PATCH")
        unchanged = {k: v for k, v in replacement.items() if k not in changes}
        check_fields(fetched, unchanged, "GET после PATCH")
        print("5. PATCH + GET: description изменено, остальные поля сохранились")

        # 7. DELETE, then GET must return the expected 404.
        client.delete_drink(created_id)
        print(f"6. DELETE: напиток id={created_id} удалён")
        try:
            client.get_drink(created_id)
        except CoffeeNotFoundError:
            print("7. GET после DELETE: получен ожидаемый 404")
            # 8. Deletion is confirmed, nothing is left to clean up.
            created_id = None
        else:
            raise ValueError("После DELETE напиток всё ещё доступен")
    except (CoffeeApiError, ValueError) as error:
        print(f"Ошибка: {error}. Метка группы: {marker}")
        if post_sent and created_id is None:
            # The POST may have created a drink even if the reply was lost.
            print(
                "Результат создания неизвестен. POST не повторяем, "
                f"проверьте вручную напиток с меткой {marker} в названии."
            )
        return 1
    finally:
        if created_id is not None:
            try:
                client.delete_drink(created_id)
            except CoffeeNotFoundError:
                pass
            except CoffeeApiError as error:
                print(f"Не удалось удалить id={created_id}: {error}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
