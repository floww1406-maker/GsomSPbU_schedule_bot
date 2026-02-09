"""
Сервис работы с расписанием.
Форматирование, нормализация и сравнение событий.
"""

import logging
from datetime import date
from typing import Any

from utils.datetime_utils import format_date_for_display, format_time_for_display, parse_api_datetime

logger = logging.getLogger(__name__)


class ScheduleService:
    """Сервис для работы с расписанием."""
    
    # Типы сессионных событий (НЕ отправлять уведомления)
    SESSION_EVENT_TYPES = [
        "зачет", "зачёт",
        "экзамен",
        "показ работ",
        "credit", "exam",
    ]
    
    # Маппинг типов занятий на русский
    EVENT_TYPE_MAP = {
        "lecture": "Лекция",
        "seminar": "Семинар",
        "practical": "Практика",
        "laboratory": "Лабораторная",
        "consultation": "Консультация",
        "exam": "Экзамен",
        "credit": "Зачёт",
        "test": "Зачёт",
        "attestation": "Аттестация",
        "project review": "Показ работ",
        "independent work": "Самостоятельная работа",
        "лекция": "Лекция",
        "семинар": "Семинар",
        "практика": "Практика",
        "лабораторная": "Лабораторная",
        "консультация": "Консультация",
        "экзамен": "Экзамен",
        "зачет": "Зачёт",
        "зачёт": "Зачёт",
        "показ работ": "Показ работ",
    }
    
    @classmethod
    def is_session_event(cls, event: dict) -> bool:
        """
        Проверка, является ли событие сессионным.
        Сессионные события: зачёт, экзамен, показ работ.
        Для них НЕ отправляются уведомления.
        """
        kind = (event.get("Kind") or "").lower()
        subject = (event.get("Subject") or "").lower()
        
        for keyword in cls.SESSION_EVENT_TYPES:
            if keyword in kind or keyword in subject:
                return True
        
        return False
    
    @classmethod
    def format_event_card(cls, event: dict) -> str:
        """
        Форматирование карточки занятия.
        Отображаются ТОЛЬКО существующие поля.
        """
        lines = []
        
        # Дата
        day_date = event.get("DayDate")
        if day_date:
            try:
                dt = parse_api_datetime(day_date + "T00:00:00")
                if dt:
                    lines.append(f"📅 {format_date_for_display(dt.date())}")
            except Exception:
                lines.append(f"📅 {day_date}")
        
        # Время
        time_start = event.get("Start") or event.get("TimeIntervalString", "").split("–")[0].strip()
        time_end = event.get("End") or ""
        if "–" in event.get("TimeIntervalString", ""):
            time_end = event.get("TimeIntervalString", "").split("–")[1].strip()
        
        if time_start:
            time_str = format_time_for_display(time_start)
            if time_end:
                time_str += f" – {format_time_for_display(time_end)}"
            lines.append(f"🕐 {time_str}")
        
        # Название предмета
        subject = event.get("Subject")
        if subject:
            lines.append(f"📚 {subject}")
        
        # Тип занятия
        kind = event.get("Kind") or ""
        if kind:
            kind_lower = kind.lower()
            kind_display = cls.EVENT_TYPE_MAP.get(kind_lower, kind)
            lines.append(f"📝 {kind_display}")
        
        # Преподаватели
        educators = event.get("EducatorIds") or event.get("Educators") or []
        if educators:
            educator_names = []
            for edu in educators:
                if isinstance(edu, dict):
                    name = edu.get("FullName") or edu.get("Name") or ""
                    if name:
                        educator_names.append(name)
                elif isinstance(edu, str):
                    educator_names.append(edu)
            
            if educator_names:
                lines.append(f"👨‍🏫 {', '.join(educator_names)}")
        
        # Аудитория / Адрес
        locations = event.get("EventLocations") or event.get("Locations") or []
        if locations:
            location_parts = []
            for loc in locations:
                if isinstance(loc, dict):
                    display = loc.get("DisplayName") or loc.get("Address") or ""
                    if display:
                        location_parts.append(display)
                elif isinstance(loc, str):
                    location_parts.append(loc)
            
            if location_parts:
                lines.append(f"📍 {', '.join(location_parts)}")
        
        # Формат обучения (онлайн)
        is_online = event.get("IsOnline") or event.get("IsCancelled") is False
        online_note = event.get("OnlineNote") or ""
        
        # Проверка на дистанционный формат
        has_online_indicator = False
        location_str = " ".join(str(loc) for loc in locations) if locations else ""
        
        online_keywords = [
            "дистанционн",
            "онлайн",
            "online",
            "коммуникационно-информационн",
            "ДОТ",
        ]
        
        for keyword in online_keywords:
            if keyword.lower() in location_str.lower() or keyword.lower() in online_note.lower():
                has_online_indicator = True
                break
        
        if has_online_indicator:
            lines.append("💻 Занятие проводится с использованием коммуникационно-информационных технологий")
        
        return "\n".join(lines)
    
    @classmethod
    def format_schedule_list(cls, events: list[dict], header: str = "") -> str:
        """
        Форматирование списка занятий.
        Сохраняет порядок событий из API.
        """
        if not events:
            return "Отдыхаем 🎉"
        
        lines = []
        if header:
            lines.append(header)
            lines.append("")
        
        for i, event in enumerate(events):
            if i > 0:
                lines.append("─" * 20)
            lines.append(cls.format_event_card(event))
        
        return "\n".join(lines)
    
    @classmethod
    def normalize_event(cls, event: dict) -> dict:
        """
        Нормализация события для сравнения.
        Извлекает ключевые поля.
        """
        # Извлечение времени
        time_start = event.get("Start") or ""
        time_end = event.get("End") or ""
        time_interval = event.get("TimeIntervalString") or ""
        
        # Извлечение преподавателей
        educators = []
        edu_data = event.get("EducatorIds") or event.get("Educators") or []
        for edu in edu_data:
            if isinstance(edu, dict):
                name = edu.get("FullName") or edu.get("Name") or ""
                if name:
                    educators.append(name)
            elif isinstance(edu, str):
                educators.append(edu)
        
        # Извлечение локаций
        locations = []
        loc_data = event.get("EventLocations") or event.get("Locations") or []
        for loc in loc_data:
            if isinstance(loc, dict):
                display = loc.get("DisplayName") or loc.get("Address") or ""
                if display:
                    locations.append(display)
            elif isinstance(loc, str):
                locations.append(loc)
        
        # Проверка онлайн формата
        location_str = " ".join(locations)
        is_online = any(
            kw in location_str.lower()
            for kw in ["дистанционн", "онлайн", "online", "коммуникационно"]
        )
        
        return {
            "date": event.get("DayDate", ""),
            "time_start": time_start,
            "time_end": time_end,
            "time_interval": time_interval,
            "subject": event.get("Subject", ""),
            "kind": event.get("Kind", ""),
            "educators": educators,  # Сохраняем порядок из API
            "locations": locations,  # Сохраняем порядок из API
            "is_online": is_online,
        }
    
    @classmethod
    def create_event_key(cls, event: dict) -> str:
        """
        Создание уникального ключа события БЕЗ времени.
        
        Ключ НЕ включает время, чтобы изменение времени определялось как "changed",
        а не как "removed + added".
        
        Ключ строится из:
        - normalized date
        - normalized subject
        - normalized lesson type/kind
        - educators list (в оригинальном порядке)
        - locations list (в оригинальном порядке)
        """
        normalized = cls.normalize_event(event)
        
        # Educators и locations конвертируем в строку
        educators_str = "|".join(normalized["educators"])
        locations_str = "|".join(normalized["locations"])
        
        return f"{normalized['date']}|{normalized['subject']}|{normalized['kind']}|{educators_str}|{locations_str}"
    
    @classmethod
    def compare_schedules(
        cls,
        old_events: list[dict],
        new_events: list[dict]
    ) -> dict[str, list[dict]]:
        """
        Сравнение двух версий расписания.
        
        Returns:
            Словарь с ключами: added, removed, changed
        """
        # Нормализуем события
        old_normalized = {
            cls.create_event_key(e): cls.normalize_event(e)
            for e in old_events
        }
        new_normalized = {
            cls.create_event_key(e): cls.normalize_event(e)
            for e in new_events
        }
        
        old_keys = set(old_normalized.keys())
        new_keys = set(new_normalized.keys())
        
        result = {
            "added": [],
            "removed": [],
            "changed": [],
        }
        
        # Добавленные занятия
        for key in new_keys - old_keys:
            # Находим оригинальное событие
            for e in new_events:
                if cls.create_event_key(e) == key:
                    result["added"].append(e)
                    break
        
        # Удалённые занятия
        for key in old_keys - new_keys:
            for e in old_events:
                if cls.create_event_key(e) == key:
                    result["removed"].append(e)
                    break
        
        # Изменённые занятия (один и тот же ключ, но разные данные)
        for key in old_keys & new_keys:
            old_data = old_normalized[key]
            new_data = new_normalized[key]
            
            changes = []
            
            if old_data["time_start"] != new_data["time_start"] or \
               old_data["time_end"] != new_data["time_end"]:
                changes.append("time")
            
            if old_data["educators"] != new_data["educators"]:
                changes.append("educator")
            
            if old_data["locations"] != new_data["locations"]:
                changes.append("location")
            
            if old_data["is_online"] != new_data["is_online"]:
                changes.append("format")
            
            if changes:
                # Находим оригинальные события
                old_event = None
                new_event = None
                for e in old_events:
                    if cls.create_event_key(e) == key:
                        old_event = e
                        break
                for e in new_events:
                    if cls.create_event_key(e) == key:
                        new_event = e
                        break
                
                result["changed"].append({
                    "old": old_event,
                    "new": new_event,
                    "changes": changes,
                })
        
        return result
    
    @classmethod
    def format_change_notification(
        cls,
        change_type: str,
        event: dict,
        changes: list[str] | None = None,
        group_name: str = ""
    ) -> str:
        """
        Форматирование уведомления об изменении.
        
        Формат по спецификации:
        1. Header: 🔔 Изменение в расписании {group}
        2. Block: Что изменилось: + list of changes
        3. Lesson card
        
        Args:
            change_type: "added", "removed", "changed"
            event: Событие
            changes: Список изменённых полей (для change_type="changed")
            group_name: Название группы
        """
        # Header
        header = f"🔔 Изменение в расписании"
        if group_name:
            header += f" {group_name}"
        
        # What changed
        what_changed = []
        if change_type == "added":
            what_changed.append("➕ Добавлено занятие")
        elif change_type == "removed":
            what_changed.append("❌ Отменено занятие")
        elif change_type == "changed" and changes:
            change_parts = []
            if "time" in changes:
                change_parts.append("время")
            if "educator" in changes:
                change_parts.append("преподаватель")
            if "location" in changes:
                change_parts.append("аудитория")
            if "format" in changes:
                change_parts.append("формат")
            what_changed.append(f"✏️ Изменено: {', '.join(change_parts)}")
        
        changes_block = "Что изменилось:\n• " + "\n• ".join(what_changed) if what_changed else ""
        
        # Lesson card
        card = cls.format_event_card(event)
        
        return f"{header}\n\n{changes_block}\n\n{card}"
