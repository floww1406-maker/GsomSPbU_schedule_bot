"""
Обработчики команд и callback-запросов.
"""

import logging
from typing import Any

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext

from config import config
from database import Database
from services.spbu_api import SpbuApiClient, SpbuApiError
from services.schedule_service import ScheduleService
from services.scheduler_service import SchedulerService
from bot.keyboards import (
    get_menu_button,
    get_start_keyboard,
    get_year_selection_keyboard,
    get_groups_keyboard,
    get_main_menu_keyboard,
    get_schedule_menu_keyboard,
    get_admin_keyboard,
)
from bot.texts import (
    START_MESSAGE,
    SELECT_YEAR_MESSAGE,
    SELECT_GROUP_MESSAGE,
    GROUP_SELECTED_MESSAGE,
    MAIN_MENU_MESSAGE,
    NO_GROUP_MESSAGE,
    SCHEDULE_MENU_MESSAGE,
    ENTER_DATE_MESSAGE,
    INVALID_DATE_MESSAGE,
    API_UNAVAILABLE_MESSAGE,
    NOTIFICATIONS_ON_MESSAGE,
    NOTIFICATIONS_OFF_MESSAGE,
    HELP_MESSAGE,
    ADMIN_STATUS_MESSAGE,
    ADMIN_CHECK_STARTED,
    ADMIN_CHECK_COMPLETED,
    LOADING_GROUPS_MESSAGE,
    NO_GROUPS_MESSAGE,
)
from bot.states import UserStates
from utils.datetime_utils import parse_date_from_user, format_date_for_display

logger = logging.getLogger(__name__)

# Роутеры
router = Router()


# ========== Зависимости (инъекция через middleware или глобально) ==========

# Глобальные объекты (инициализируются в main.py)
db: Database | None = None
api_client: SpbuApiClient | None = None
scheduler_service: SchedulerService | None = None

# Кэш групп по годам
_groups_cache: dict[int, list[dict]] = {}


def setup_dependencies(
    database: Database,
    api: SpbuApiClient,
    scheduler: SchedulerService
) -> None:
    """Настройка зависимостей."""
    global db, api_client, scheduler_service
    db = database
    api_client = api
    scheduler_service = scheduler


# ========== Вспомогательные функции ==========

async def get_groups_for_year(year: int) -> list[dict]:
    """Получение групп для года с кэшированием."""
    if year in _groups_cache:
        return _groups_cache[year]
    
    if api_client is None:
        return []
    
    try:
        groups = await api_client.get_bachelor_groups_by_year(year)
        _groups_cache[year] = groups
        return groups
    except SpbuApiError:
        return []


async def send_schedule_response(
    callback: CallbackQuery,
    events: list[dict],
    header: str = ""
) -> None:
    """Отправка форматированного расписания."""
    text = ScheduleService.format_schedule_list(events, header)
    
    # Telegram limit 4096 chars
    if len(text) > 4000:
        # Разбиваем на части
        parts = []
        current_part = ""
        
        for line in text.split("\n"):
            if len(current_part) + len(line) + 1 > 3900:
                parts.append(current_part)
                current_part = line
            else:
                current_part = current_part + "\n" + line if current_part else line
        
        if current_part:
            parts.append(current_part)
        
        # Кнопка "Меню" на КАЖДОМ чанке
        for part in parts:
            await callback.message.answer(part, reply_markup=get_menu_button())
    else:
        await callback.message.answer(text, reply_markup=get_menu_button())


# ========== Команды ==========

@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext) -> None:
    """Обработка команды /start."""
    await state.clear()
    
    if db:
        # Создаём пользователя если не существует
        user = await db.get_user(message.from_user.id)
        if not user:
            await db.create_or_update_user(message.from_user.id)
    
    await message.answer(START_MESSAGE, reply_markup=get_start_keyboard())


@router.message(Command("menu"))
async def cmd_menu(message: Message, state: FSMContext) -> None:
    """Обработка команды /menu."""
    await state.clear()
    await show_main_menu(message)


@router.message(Command("admin"))
async def cmd_admin(message: Message) -> None:
    """Обработка скрытой команды /admin."""
    if message.from_user.id != config.ADMIN_ID:
        # Игнорируем для не-админов
        return
    
    await message.answer("🔐 Админ-панель", reply_markup=get_admin_keyboard())


# ========== Callback handlers ==========

@router.callback_query(F.data == "menu")
async def callback_menu(callback: CallbackQuery, state: FSMContext) -> None:
    """Возврат в главное меню."""
    await state.clear()
    await callback.answer()
    await show_main_menu(callback.message)


@router.callback_query(F.data == "select_year")
async def callback_select_year(callback: CallbackQuery) -> None:
    """Выбор года поступления."""
    await callback.answer()
    await callback.message.edit_text(
        SELECT_YEAR_MESSAGE,
        reply_markup=get_year_selection_keyboard()
    )


@router.callback_query(F.data.startswith("year:"))
async def callback_year_selected(callback: CallbackQuery) -> None:
    """Обработка выбора года."""
    year = int(callback.data.split(":")[1])
    await callback.answer()
    
    # Показываем индикатор загрузки
    await callback.message.edit_text(LOADING_GROUPS_MESSAGE)
    
    # Загружаем группы
    groups = await get_groups_for_year(year)
    
    if not groups:
        await callback.message.edit_text(
            NO_GROUPS_MESSAGE,
            reply_markup=get_menu_button()
        )
        return
    
    await callback.message.edit_text(
        SELECT_GROUP_MESSAGE,
        reply_markup=get_groups_keyboard(groups, page=0, year=year)
    )


@router.callback_query(F.data.startswith("groups_page:"))
async def callback_groups_page(callback: CallbackQuery) -> None:
    """Пагинация групп."""
    _, year_str, page_str = callback.data.split(":")
    year = int(year_str)
    page = int(page_str)
    
    await callback.answer()
    
    groups = await get_groups_for_year(year)
    
    if not groups:
        await callback.message.edit_text(
            NO_GROUPS_MESSAGE,
            reply_markup=get_menu_button()
        )
        return
    
    await callback.message.edit_text(
        SELECT_GROUP_MESSAGE,
        reply_markup=get_groups_keyboard(groups, page=page, year=year)
    )


@router.callback_query(F.data.startswith("group:"))
async def callback_group_selected(callback: CallbackQuery) -> None:
    """Обработка выбора группы."""
    parts = callback.data.split(":")
    group_id = int(parts[1])
    group_name = parts[2] if len(parts) > 2 else "Группа"
    
    await callback.answer()
    
    if db:
        await db.set_user_group(callback.from_user.id, group_id, group_name)
    
    await callback.message.edit_text(
        GROUP_SELECTED_MESSAGE.format(group_name=group_name),
        reply_markup=get_menu_button()
    )


@router.callback_query(F.data == "toggle_notifications")
async def callback_toggle_notifications(callback: CallbackQuery) -> None:
    """Переключение уведомлений."""
    if not db:
        await callback.answer("Ошибка")
        return
    
    new_state = await db.toggle_notifications(callback.from_user.id)
    
    if new_state:
        await callback.answer(NOTIFICATIONS_ON_MESSAGE, show_alert=True)
    else:
        await callback.answer(NOTIFICATIONS_OFF_MESSAGE, show_alert=True)
    
    # Обновляем меню
    await show_main_menu(callback.message, edit=True)


@router.callback_query(F.data == "schedule_menu")
async def callback_schedule_menu(callback: CallbackQuery) -> None:
    """Меню расписания."""
    await callback.answer()
    
    if not db:
        return
    
    user = await db.get_user(callback.from_user.id)
    if not user or not user.get("group_id"):
        await callback.message.edit_text(
            NO_GROUP_MESSAGE,
            reply_markup=get_menu_button()
        )
        return
    
    await callback.message.edit_text(
        SCHEDULE_MENU_MESSAGE,
        reply_markup=get_schedule_menu_keyboard()
    )


@router.callback_query(F.data.startswith("schedule:"))
async def callback_schedule(callback: CallbackQuery, state: FSMContext) -> None:
    """Обработка запросов расписания."""
    schedule_type = callback.data.split(":")[1]
    
    if not db or not api_client:
        await callback.answer("Ошибка")
        return
    
    user = await db.get_user(callback.from_user.id)
    if not user or not user.get("group_id"):
        await callback.answer()
        await callback.message.edit_text(
            NO_GROUP_MESSAGE,
            reply_markup=get_menu_button()
        )
        return
    
    group_id = user["group_id"]
    await callback.answer()
    
    # Ввод даты - переход в состояние
    if schedule_type == "date":
        await state.set_state(UserStates.waiting_for_date)
        await callback.message.edit_text(
            ENTER_DATE_MESSAGE,
            reply_markup=get_menu_button()
        )
        return
    
    # Загружаем расписание
    try:
        if schedule_type == "today":
            events = await api_client.get_group_schedule_today(group_id)
            header = "📅 Расписание на сегодня:"
        elif schedule_type == "tomorrow":
            events = await api_client.get_group_schedule_tomorrow(group_id)
            header = "📅 Расписание на завтра:"
        elif schedule_type == "week":
            events = await api_client.get_group_schedule_week(group_id)
            header = "📅 Расписание на неделю:"
        elif schedule_type == "session":
            events = await api_client.get_group_session_schedule(group_id)
            header = "📚 Расписание сессии (зачёты, экзамены, показы работ):"
        else:
            await callback.message.answer("Неизвестный тип расписания", reply_markup=get_menu_button())
            return
        
        await send_schedule_response(callback, events, header)
    
    except SpbuApiError:
        await callback.message.answer(
            API_UNAVAILABLE_MESSAGE,
            reply_markup=get_menu_button()
        )


@router.callback_query(F.data == "help")
async def callback_help(callback: CallbackQuery) -> None:
    """Показ помощи."""
    await callback.answer()
    await callback.message.edit_text(
        HELP_MESSAGE,
        reply_markup=get_menu_button()
    )


# ========== Админ handlers ==========

@router.callback_query(F.data == "admin:status")
async def callback_admin_status(callback: CallbackQuery) -> None:
    """Статус системы для админа."""
    if callback.from_user.id != config.ADMIN_ID:
        await callback.answer("Доступ запрещён", show_alert=True)
        return
    
    await callback.answer()
    
    if not db:
        return
    
    stats = await db.get_stats()
    
    text = ADMIN_STATUS_MESSAGE.format(
        total_users=stats.get("total_users", 0),
        users_with_groups=stats.get("users_with_groups", 0),
        notifications_enabled=stats.get("notifications_enabled", 0),
        unique_groups=stats.get("unique_groups", 0),
        last_schedule_check=stats.get("last_schedule_check") or "никогда",
        last_session_check=stats.get("last_session_check") or "никогда",
        last_error=stats.get("last_error") or "нет",
    )
    
    await callback.message.edit_text(text, reply_markup=get_admin_keyboard())


@router.callback_query(F.data == "admin:check")
async def callback_admin_check(callback: CallbackQuery) -> None:
    """Ручной запуск проверки расписания."""
    if callback.from_user.id != config.ADMIN_ID:
        await callback.answer("Доступ запрещён", show_alert=True)
        return
    
    await callback.answer()
    await callback.message.edit_text(ADMIN_CHECK_STARTED)
    
    if scheduler_service:
        result = await scheduler_service.trigger_manual_check()
        
        await callback.message.edit_text(
            ADMIN_CHECK_COMPLETED.format(duration=result["duration_seconds"]),
            reply_markup=get_admin_keyboard()
        )


# ========== Состояния FSM ==========

@router.message(UserStates.waiting_for_date)
async def process_date_input(message: Message, state: FSMContext) -> None:
    """Обработка ввода даты."""
    date_input = message.text.strip()
    parsed_date = parse_date_from_user(date_input)
    
    if not parsed_date:
        await message.answer(
            INVALID_DATE_MESSAGE,
            reply_markup=get_menu_button()
        )
        return
    
    await state.clear()
    
    if not db or not api_client:
        return
    
    user = await db.get_user(message.from_user.id)
    if not user or not user.get("group_id"):
        await message.answer(
            NO_GROUP_MESSAGE,
            reply_markup=get_menu_button()
        )
        return
    
    try:
        events = await api_client.get_group_schedule_date(user["group_id"], parsed_date)
        header = f"📅 Расписание на {format_date_for_display(parsed_date)}:"
        
        text = ScheduleService.format_schedule_list(events, header)
        await message.answer(text, reply_markup=get_menu_button())
    
    except SpbuApiError:
        await message.answer(
            API_UNAVAILABLE_MESSAGE,
            reply_markup=get_menu_button()
        )


# ========== Вспомогательные функции ==========

async def show_main_menu(message: Message, edit: bool = False) -> None:
    """Показ главного меню."""
    if not db:
        return
    
    user = await db.get_user(message.chat.id)
    
    if user and user.get("group_id"):
        group_name = user.get("group_name", "Не указана")
        notifications_enabled = bool(user.get("notifications_enabled", True))
        notifications_status = "включены ✅" if notifications_enabled else "выключены ❌"
        
        text = MAIN_MENU_MESSAGE.format(
            group_name=group_name,
            notifications_status=notifications_status
        )
        keyboard = get_main_menu_keyboard(notifications_enabled)
    else:
        text = NO_GROUP_MESSAGE
        keyboard = get_start_keyboard()
    
    if edit:
        await message.edit_text(text, reply_markup=keyboard)
    else:
        await message.answer(text, reply_markup=keyboard)
