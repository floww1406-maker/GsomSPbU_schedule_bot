"""
Утилиты для работы с датой и временем.
Все операции в часовом поясе Санкт-Петербурга (UTC+3).
"""

from datetime import datetime, date, timedelta
import pytz

from config import config

# Часовой пояс Санкт-Петербурга
SPB_TZ = pytz.timezone(config.TIMEZONE)


def now() -> datetime:
    """Текущее время в часовом поясе Санкт-Петербурга."""
    return datetime.now(SPB_TZ)


def today() -> date:
    """Текущая дата в часовом поясе Санкт-Петербурга."""
    return now().date()


def format_date_for_api(dt: date) -> str:
    """
    Форматирование даты для API SPbU.
    Формат: YYYY-MM-DD (например, 2024-09-28).
    """
    return dt.strftime("%Y-%m-%d")


def format_date_for_api_end(dt: date) -> str:
    """
    Форматирование даты для API SPbU (конец периода).
    Формат: YYYY-MM-DD (например, 2024-09-28).
    """
    return dt.strftime("%Y-%m-%d")


def parse_date_from_user(date_str: str) -> date | None:
    """
    Парсинг даты введённой пользователем.
    Ожидаемый формат: DD.MM.YYYY
    Возвращает None при ошибке.
    """
    try:
        return datetime.strptime(date_str.strip(), "%d.%m.%Y").date()
    except ValueError:
        return None


def format_date_for_display(dt: date) -> str:
    """Форматирование даты для отображения пользователю."""
    weekdays = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    weekday = weekdays[dt.weekday()]
    return f"{weekday}, {dt.strftime('%d.%m.%Y')}"


def format_time_for_display(time_str: str) -> str:
    """
    Форматирование времени для отображения.
    Входной формат из API: HH:MM или различные варианты.
    """
    if not time_str:
        return ""
    # Убираем секунды если есть
    if time_str.count(":") == 2:
        return time_str[:5]
    return time_str


def get_date_range(days: int) -> tuple[date, date]:
    """
    Получение диапазона дат: N календарных дней включая сегодня.
    
    Args:
        days: Количество дней (включая сегодня)
    
    Returns:
        (start, end) - обе даты включительно
    """
    start = today()
    end = start + timedelta(days=days - 1)  # end date is inclusive
    return start, end


def parse_api_datetime(dt_str: str) -> datetime | None:
    """
    Парсинг даты/времени из API SPbU.
    Формат API: 2024-09-28T08:00:00 или похожий.
    """
    if not dt_str:
        return None
    
    formats = [
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
    ]
    
    for fmt in formats:
        try:
            dt = datetime.strptime(dt_str, fmt)
            return SPB_TZ.localize(dt)
        except ValueError:
            continue
    
    return None


def get_current_year() -> int:
    """Получение текущего года."""
    return now().year
