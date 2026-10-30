from uuid import uuid4

from app.client import SampleApisCoffeeClient
from app.exceptions import CoffeeApiError, CoffeeNotFoundError


def main() -> int:
    client = SampleApisCoffeeClient()
    marker = uuid4().hex[:8]
    created_id = None
    try:
        # GET коллекции.
        # POST: исследуйте поля, добавьте marker в название.
        # Сразу сохраните id из ответа в created_id.
        # GET: сравните сохранённые поля с отправленными.
        # PUT и повторный GET: проверьте все заменённые поля.
        # PATCH и повторный GET: проверьте изменённое поле
        # и убедитесь, что остальные поля сохранились.
        # DELETE и GET: убедитесь, что вернулся ожидаемый 404.
        # После подтверждения удаления: created_id = None.
        raise NotImplementedError("Заполните этапы сценария")
    except (CoffeeApiError, ValueError) as error:
        print(f"Ошибка: {error}. Метка группы: {marker}")
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
