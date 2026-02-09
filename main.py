"""
Главный модуль запуска бота.
"""

import asyncio
import logging
import sys
import os

# Добавляем корневую директорию в PYTHONPATH для Railway
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from config import config
from database import Database
from services.spbu_api import SpbuApiClient
from services.scheduler_service import SchedulerService
from bot.handlers import router, setup_dependencies

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ]
)

logger = logging.getLogger(__name__)


async def on_startup(bot: Bot, db: Database, scheduler: SchedulerService) -> None:
    """Действия при запуске бота."""
    logger.info("Bot starting...")
    
    # Запуск планировщика
    await scheduler.start()
    
    # Уведомление админа
    try:
        await bot.send_message(
            config.ADMIN_ID,
            "🟢 Бот запущен и готов к работе!"
        )
    except Exception as e:
        logger.warning(f"Failed to notify admin: {e}")
    
    logger.info("Bot started successfully!")


async def on_shutdown(bot: Bot, db: Database, scheduler: SchedulerService, api_client: SpbuApiClient) -> None:
    """Действия при остановке бота."""
    logger.info("Bot shutting down...")
    
    # Остановка планировщика
    await scheduler.stop()
    
    # Закрытие соединений
    await api_client.close()
    await db.close()
    
    # Уведомление админа
    try:
        await bot.send_message(
            config.ADMIN_ID,
            "🔴 Бот остановлен."
        )
    except Exception:
        pass
    
    logger.info("Bot stopped.")


async def main() -> None:
    """Главная функция запуска."""
    # Валидация конфигурации
    try:
        config.validate()
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        sys.exit(1)
    
    # Создание директории для данных
    config.ensure_data_dir()
    
    # Инициализация компонентов
    bot = Bot(token=config.BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    
    # База данных
    db = Database()
    await db.connect()
    logger.info("Database connected")
    
    # API клиент
    api_client = SpbuApiClient()
    await api_client.start()
    logger.info("API client started")
    
    # Планировщик
    scheduler = SchedulerService(bot, db, api_client)
    
    # Настройка зависимостей для handlers
    setup_dependencies(db, api_client, scheduler)
    
    # Регистрация роутеров
    dp.include_router(router)
    
    # Startup и shutdown hooks (правильный способ для aiogram 3.x)
    @dp.startup()
    async def startup_handler():
        await on_startup(bot, db, scheduler)
    
    @dp.shutdown()
    async def shutdown_handler():
        await on_shutdown(bot, db, scheduler, api_client)
    
    # Запуск polling
    logger.info("Starting polling...")
    
    try:
        await dp.start_polling(
            bot,
            allowed_updates=["message", "callback_query"],
            drop_pending_updates=True  # Пропускаем накопившиеся обновления
        )
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.exception(f"Fatal error: {e}")
        sys.exit(1)
