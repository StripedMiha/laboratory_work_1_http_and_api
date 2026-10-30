class CoffeeApiError(Exception):
    """Ошибка при обращении к SampleAPIs Coffee."""


class CoffeeNotFoundError(CoffeeApiError):
    """Ресурс не найден (ожидаемый HTTP 404)."""
