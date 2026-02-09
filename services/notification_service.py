"""
Сервис уведомлений.
Отправка уведомлений об изменениях в расписании.
"""

import logging
from typing import TYPE_CHECKING

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest

from database import Database
from services.schedule_service import ScheduleService
from utils.datetime_utils import now

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


def get_menu_button_markup() -> InlineKeyboardMarkup:
    """Получение клавиатуры с кнопкой Меню для уведомлений."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Меню", callback_data="menu")]
    ])


class NotificationService:
    """Сервис отправки уведомлений."""
    
    def __init__(self, bot: Bot, db: Database):
        self.bot = bot
        self.db = db
    
    async def send_notification(self, user_id: int, text: str, with_menu: bool = True) -> bool:
        """
        Отправка уведомления пользователю.
        
        Args:
            user_id: ID пользователя
            text: Текст уведомления
            with_menu: Добавить кнопку "Меню" (по умолчанию True)
        
        Returns:
            True если уведомление отправлено успешно
        """
        try:
            reply_markup = get_menu_button_markup() if with_menu else None
            await self.bot.send_message(
                chat_id=user_id,
                text=text,
                reply_markup=reply_markup,
                parse_mode=None  # Без форматирования для стабильности
            )
            return True
        
        except TelegramForbiddenError:
            # Пользователь заблокировал бота
            logger.info(f"User {user_id} blocked the bot")
            return False
        
        except TelegramBadRequest as e:
            logger.error(f"Bad request for user {user_id}: {e}")
            return False
        
        except Exception as e:
            logger.error(f"Failed to send notification to {user_id}: {e}")
            return False
    
    async def notify_schedule_changes(
        self,
        group_id: int,
        old_events: list[dict],
        new_events: list[dict]
    ) -> int:
        """
        Уведомление пользователей об изменениях в расписании.
        
        Returns:
            Количество отправленных уведомлений
        """
        # Сравнение расписаний
        changes = ScheduleService.compare_schedules(old_events, new_events)
        
        if not any([changes["added"], changes["removed"], changes["changed"]]):
            return 0
        
        # Получение пользователей группы с включёнными уведомлениями
        users = await self.db.get_users_by_group(group_id, notifications_only=True)
        
        if not users:
            return 0
        
        # Получаем название группы из первого пользователя
        group_name = users[0].get("group_name", "") if users else ""
        
        sent_count = 0
        
        # Формируем уведомления
        notifications = []
        
        # Добавленные занятия (исключая сессионные)
        for event in changes["added"]:
            # НЕ отправляем уведомления для сессионных событий
            if ScheduleService.is_session_event(event):
                continue
            notification_text = ScheduleService.format_change_notification(
                "added", event, group_name=group_name
            )
            notification_data = {
                "type": "added",
                "event_key": ScheduleService.create_event_key(event),
            }
            notifications.append((notification_text, notification_data))
        
        # Удалённые занятия (исключая сессионные)
        for event in changes["removed"]:
            # НЕ отправляем уведомления для сессионных событий
            if ScheduleService.is_session_event(event):
                continue
            notification_text = ScheduleService.format_change_notification(
                "removed", event, group_name=group_name
            )
            notification_data = {
                "type": "removed",
                "event_key": ScheduleService.create_event_key(event),
            }
            notifications.append((notification_text, notification_data))
        
        # Изменённые занятия (исключая сессионные)
        for change in changes["changed"]:
            # НЕ отправляем уведомления для сессионных событий
            if ScheduleService.is_session_event(change["new"]):
                continue
            notification_text = ScheduleService.format_change_notification(
                "changed",
                change["new"],
                change["changes"],
                group_name=group_name
            )
            notification_data = {
                "type": "changed",
                "event_key": ScheduleService.create_event_key(change["new"]),
                "changes": change["changes"],
            }
            notifications.append((notification_text, notification_data))
        
        # Отправка уведомлений каждому пользователю
        for user in users:
            user_id = user["user_id"]
            
            for notification_text, notification_data in notifications:
                # Проверка на дубликат
                if await self.db.is_notification_sent(user_id, notification_data):
                    continue
                
                # Отправка (с кнопкой Меню)
                if await self.send_notification(user_id, notification_text, with_menu=True):
                    await self.db.mark_notification_sent(user_id, notification_data)
                    sent_count += 1
        
        return sent_count
    
    async def send_admin_alert(self, admin_id: int, message: str) -> bool:
        """Отправка уведомления администратору."""
        text = f"🔔 Системное уведомление\n\n{message}\n\n⏰ {now().strftime('%d.%m.%Y %H:%M')}"
        return await self.send_notification(admin_id, text)
