"""
FSM состояния бота.
"""

from aiogram.fsm.state import State, StatesGroup


class UserStates(StatesGroup):
    """Состояния пользователя."""
    
    # Ввод даты для просмотра расписания
    waiting_for_date = State()
