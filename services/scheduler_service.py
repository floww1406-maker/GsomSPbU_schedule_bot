"""
Планировщик проверки расписания.
Периодическая проверка изменений и отправка уведомлений.
"""

import logging
from datetime import datetime

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from config import config
from database import Database
from services.spbu_api import SpbuApiClient, SpbuApiError
from services.notification_service import NotificationService
from utils.datetime_utils import now

logger = logging.getLogger(__name__)


class SchedulerService:
    """Сервис планировщика задач."""
    
    def __init__(self, bot: Bot, db: Database, api_client: SpbuApiClient):
        self.bot = bot
        self.db = db
        self.api_client = api_client
        self.notification_service = NotificationService(bot, db)
        self.scheduler = AsyncIOScheduler(timezone=config.TIMEZONE)
    
    async def start(self) -> None:
        """Запуск планировщика."""
        # Задача проверки регулярного расписания
        self.scheduler.add_job(
            self.check_schedule_changes,
            IntervalTrigger(minutes=config.CHECK_INTERVAL_MINUTES),
            id="check_schedule",
            name="Check schedule changes",
            replace_existing=True,
        )
        
        self.scheduler.start()
        logger.info(f"Scheduler started. Check interval: {config.CHECK_INTERVAL_MINUTES} minutes")
    
    async def stop(self) -> None:
        """Остановка планировщика."""
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
            logger.info("Scheduler stopped")
    
    async def check_schedule_changes(self) -> None:
        """
        Проверка изменений расписания для всех групп.
        Вызывается периодически планировщиком.
        """
        logger.info("Starting schedule check...")
        
        try:
            # Получаем все уникальные группы
            group_ids = await self.db.get_all_unique_groups()
            
            if not group_ids:
                logger.info("No groups to check")
                return
            
            total_notifications = 0
            errors = []
            
            for group_id in group_ids:
                try:
                    notifications = await self._check_group_schedule(group_id)
                    total_notifications += notifications
                except Exception as e:
                    logger.error(f"Error checking group {group_id}: {e}")
                    errors.append(f"Group {group_id}: {e}")
            
            # Обновляем системное состояние для регулярного расписания
            await self.db.set_system_state(
                "last_schedule_check",
                now().strftime("%Y-%m-%d %H:%M:%S")
            )
            
            # Проверка сессии с throttle (не чаще раза в 6 часов)
            await self._maybe_check_session(group_ids)
            
            if errors:
                await self.db.set_system_state(
                    "last_error",
                    f"{now().strftime('%Y-%m-%d %H:%M:%S')}: {'; '.join(errors[:3])}"
                )
            
            logger.info(f"Schedule check completed. Groups: {len(group_ids)}, Notifications: {total_notifications}")
        
        except Exception as e:
            logger.error(f"Schedule check failed: {e}")
            await self.db.set_system_state(
                "last_error",
                f"{now().strftime('%Y-%m-%d %H:%M:%S')}: {str(e)}"
            )
    
    async def _maybe_check_session(self, group_ids: list[int]) -> None:
        """
        Проверка сессии с ограничением частоты (не чаще раза в 6 часов).
        """
        from datetime import datetime, timedelta
        
        SESSION_CHECK_INTERVAL_HOURS = 6
        
        # Проверяем время последней проверки сессии
        last_check_str = await self.db.get_system_state("last_session_check")
        
        if last_check_str:
            try:
                last_check = datetime.strptime(last_check_str, "%Y-%m-%d %H:%M:%S")
                time_since_last = now().replace(tzinfo=None) - last_check
                
                if time_since_last < timedelta(hours=SESSION_CHECK_INTERVAL_HOURS):
                    logger.debug(f"Session check skipped (last check {time_since_last} ago)")
                    return
            except ValueError:
                pass  # Невалидная дата - выполняем проверку
        
        # Выполняем проверку сессии
        if await self._check_session_data(group_ids):
            await self.db.set_system_state(
                "last_session_check",
                now().strftime("%Y-%m-%d %H:%M:%S")
            )
    
    async def _check_session_data(self, group_ids: list[int]) -> bool:
        """
        Проверка доступности данных сессии (без уведомлений).
        Выполняет реальный запрос к API для одной группы.
        
        Returns:
            True если запрос успешен
        """
        if not group_ids:
            return False
        
        # Проверяем сессию для первой группы (достаточно для проверки API)
        try:
            await self.api_client.get_group_session_schedule(group_ids[0])
            logger.info("Session data check successful")
            return True
        except SpbuApiError as e:
            logger.warning(f"Session data check failed: {e}")
            return False
    
    async def _check_group_schedule(self, group_id: int) -> int:
        """
        Проверка расписания конкретной группы.
        
        Returns:
            Количество отправленных уведомлений
        """
        # Получаем текущее расписание из API
        try:
            new_events = await self.api_client.get_group_schedule_regular(group_id)
        except SpbuApiError as e:
            logger.error(f"Failed to fetch schedule for group {group_id}: {e}")
            raise
        
        # Получаем сохранённый снимок
        old_hash, old_events = await self.db.get_schedule_snapshot(group_id, "regular")
        
        if old_events is None:
            # Первый запуск - сохраняем снимок без уведомлений
            await self.db.save_schedule_snapshot(group_id, new_events, "regular")
            logger.info(f"Initial snapshot saved for group {group_id}")
            return 0
        
        # Вычисляем новый хеш
        new_hash = self.db._hash_schedule(new_events)
        
        # Если хеши совпадают - изменений нет
        if old_hash == new_hash:
            return 0
        
        # Отправляем уведомления об изменениях
        notifications_sent = await self.notification_service.notify_schedule_changes(
            group_id,
            old_events,
            new_events
        )
        
        # Сохраняем новый снимок
        await self.db.save_schedule_snapshot(group_id, new_events, "regular")
        
        logger.info(f"Group {group_id}: {notifications_sent} notifications sent")
        return notifications_sent
    
    async def trigger_manual_check(self) -> dict:
        """
        Ручной запуск проверки (для админки).
        
        Returns:
            Статистика проверки
        """
        start_time = now()
        
        await self.check_schedule_changes()
        
        end_time = now()
        duration = (end_time - start_time).total_seconds()
        
        return {
            "started_at": start_time.strftime("%Y-%m-%d %H:%M:%S"),
            "duration_seconds": duration,
        }
