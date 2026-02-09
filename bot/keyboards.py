"""
Клавиатуры бота.
Inline кнопки для навигации.
"""

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import config
from utils.datetime_utils import get_current_year


def get_menu_button() -> InlineKeyboardMarkup:
    """Универсальная кнопка 'Меню'."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Меню", callback_data="menu")]
    ])


def get_start_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура для /start."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Выбрать год поступления", callback_data="select_year")]
    ])


def get_year_selection_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора года поступления."""
    builder = InlineKeyboardBuilder()
    
    current_year = get_current_year()
    start_year = config.START_YEAR
    
    # Добавляем года от START_YEAR до текущего
    for year in range(start_year, current_year + 1):
        builder.button(
            text=str(year),
            callback_data=f"year:{year}"
        )
    
    # По 2 кнопки в ряд
    builder.adjust(2)
    
    # Кнопка меню
    builder.row(InlineKeyboardButton(text="Меню", callback_data="menu"))
    
    return builder.as_markup()


def get_groups_keyboard(
    groups: list[dict],
    page: int = 0,
    year: int = 0
) -> InlineKeyboardMarkup:
    """
    Клавиатура выбора группы с пагинацией.
    
    Args:
        groups: Список групп
        page: Номер страницы (с 0)
        year: Год поступления (для callback)
    """
    builder = InlineKeyboardBuilder()
    
    per_page = config.GROUPS_PER_PAGE
    total_pages = (len(groups) + per_page - 1) // per_page
    
    # Группы для текущей страницы
    start_idx = page * per_page
    end_idx = min(start_idx + per_page, len(groups))
    page_groups = groups[start_idx:end_idx]
    
    # Кнопки групп
    for group in page_groups:
        group_id = group.get("StudentGroupId")
        group_name = group.get("StudentGroupName", "Группа")
        builder.button(
            text=group_name,
            callback_data=f"group:{group_id}:{group_name[:30]}"
        )
    
    # По 1 кнопке в ряд
    builder.adjust(1)
    
    # Кнопка "Далее" если есть следующая страница
    if page + 1 < total_pages:
        builder.row(InlineKeyboardButton(
            text="Далее →",
            callback_data=f"groups_page:{year}:{page + 1}"
        ))
    
    # Кнопка меню
    builder.row(InlineKeyboardButton(text="Меню", callback_data="menu"))
    
    return builder.as_markup()


def get_main_menu_keyboard(notifications_enabled: bool = True) -> InlineKeyboardMarkup:
    """Главное меню."""
    notification_text = "🔔 Уведомления: вкл" if notifications_enabled else "🔕 Уведомления: выкл"
    
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎓 Выбрать группу", callback_data="select_year")],
        [InlineKeyboardButton(text=notification_text, callback_data="toggle_notifications")],
        [InlineKeyboardButton(text="📅 Расписание", callback_data="schedule_menu")],
        [InlineKeyboardButton(text="❓ Помощь", callback_data="help")],
    ])


def get_schedule_menu_keyboard() -> InlineKeyboardMarkup:
    """Меню расписания."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Сегодня", callback_data="schedule:today")],
        [InlineKeyboardButton(text="Завтра", callback_data="schedule:tomorrow")],
        [InlineKeyboardButton(text="Неделя", callback_data="schedule:week")],
        [InlineKeyboardButton(text="Дата", callback_data="schedule:date")],
        [InlineKeyboardButton(text="Сессия", callback_data="schedule:session")],
        [InlineKeyboardButton(text="Меню", callback_data="menu")],
    ])


def get_admin_keyboard() -> InlineKeyboardMarkup:
    """Админ-панель."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статус системы", callback_data="admin:status")],
        [InlineKeyboardButton(text="🔄 Проверить расписание", callback_data="admin:check")],
        [InlineKeyboardButton(text="Меню", callback_data="menu")],
    ])
