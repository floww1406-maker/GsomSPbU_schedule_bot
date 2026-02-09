"""
Конфигурация бота.
Все настройки загружаются из переменных окружения.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Загрузка переменных окружения из .env файла
load_dotenv()


class Config:
    """Конфигурация приложения."""
    
    # Telegram Bot
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    ADMIN_ID: int = int(os.getenv("ADMIN_ID", "0"))
    
    # Database
    DATABASE_PATH: str = os.getenv("DATABASE_PATH", "data/bot.db")
    
    # Scheduler
    CHECK_INTERVAL_MINUTES: int = int(os.getenv("CHECK_INTERVAL_MINUTES", "10"))
    
    # SPbU API
    SPBU_API_URL: str = os.getenv("SPBU_API_URL", "https://timetable.spbu.ru/api/v1")
    GSOM_ALIAS: str = os.getenv("GSOM_ALIAS", "GSOM")
    
    # Schedule windows (days)
    REGULAR_SCHEDULE_DAYS: int = 14  # today + 14 days
    SESSION_SCHEDULE_DAYS: int = 90  # today + 90 days
    
    # Pagination
    GROUPS_PER_PAGE: int = 8
    
    # Timezone
    TIMEZONE: str = "Europe/Moscow"  # UTC+3 (Saint Petersburg)
    
    # Years range for admission year selection
    START_YEAR: int = 2022
    
    @classmethod
    def validate(cls) -> None:
        """Проверка обязательных настроек."""
        if not cls.BOT_TOKEN:
            raise ValueError("BOT_TOKEN is required")
        if not cls.ADMIN_ID:
            raise ValueError("ADMIN_ID is required")
    
    @classmethod
    def ensure_data_dir(cls) -> None:
        """Создание директории для базы данных."""
        db_dir = Path(cls.DATABASE_PATH).parent
        db_dir.mkdir(parents=True, exist_ok=True)


config = Config()
