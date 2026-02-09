"""Сервисы."""

from services.spbu_api import SpbuApiClient
from services.schedule_service import ScheduleService
from services.notification_service import NotificationService

__all__ = ["SpbuApiClient", "ScheduleService", "NotificationService"]
