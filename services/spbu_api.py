"""
Клиент для работы с API расписания СПбГУ.
API документация: https://timetable.spbu.ru/help/ui/index
"""

import aiohttp
import logging
from datetime import date
from typing import Any

from config import config
from utils.datetime_utils import format_date_for_api, format_date_for_api_end

logger = logging.getLogger(__name__)


class SpbuApiError(Exception):
    """Ошибка API СПбГУ."""
    pass


class SpbuApiClient:
    """Асинхронный клиент для API расписания СПбГУ."""
    
    def __init__(self, base_url: str | None = None):
        self.base_url = (base_url or config.SPBU_API_URL).rstrip("/")
        self._session: aiohttp.ClientSession | None = None
    
    async def __aenter__(self) -> "SpbuApiClient":
        await self.start()
        return self
    
    async def __aexit__(self, *args) -> None:
        await self.close()
    
    async def start(self) -> None:
        """Создание HTTP сессии."""
        if self._session is None:
            timeout = aiohttp.ClientTimeout(total=30)
            self._session = aiohttp.ClientSession(timeout=timeout)
    
    async def close(self) -> None:
        """Закрытие HTTP сессии."""
        if self._session:
            await self._session.close()
            self._session = None
    
    @property
    def session(self) -> aiohttp.ClientSession:
        """Получение сессии с проверкой."""
        if not self._session:
            raise RuntimeError("SpbuApiClient not started. Call start() first.")
        return self._session
    
    async def _request(self, endpoint: str, max_retries: int = 3) -> Any:
        """
        Выполнение запроса к API с retry и backoff.
        
        Args:
            endpoint: Эндпоинт API (без базового URL)
            max_retries: Максимальное количество попыток
        
        Returns:
            JSON ответ от API
        
        Raises:
            SpbuApiError: При ошибке запроса после всех попыток
        """
        import asyncio
        
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        last_error = None
        
        for attempt in range(max_retries):
            try:
                async with self.session.get(url) as response:
                    if response.status == 200:
                        return await response.json()
                    
                    # Retry на 5xx ошибки
                    if response.status >= 500:
                        last_error = SpbuApiError(f"API returned status {response.status}")
                        logger.warning(f"API 5xx error (attempt {attempt + 1}/{max_retries}): {response.status} for {url}")
                        if attempt < max_retries - 1:
                            await asyncio.sleep(2 ** attempt)  # Exponential backoff: 1, 2, 4 sec
                            continue
                    
                    # Не retry на 4xx
                    logger.error(f"API error: {response.status} for {url}")
                    raise SpbuApiError(f"API returned status {response.status}")
            
            except aiohttp.ClientError as e:
                last_error = SpbuApiError(f"HTTP error: {e}")
                logger.warning(f"HTTP error (attempt {attempt + 1}/{max_retries}): {e} for {url}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue
            except SpbuApiError:
                raise
            except Exception as e:
                logger.error(f"Unexpected error: {e} for {url}")
                raise SpbuApiError(f"Unexpected error: {e}")
        
        # Все попытки исчерпаны
        logger.error(f"All {max_retries} attempts failed for {url}")
        raise last_error or SpbuApiError("Request failed after retries")
    
    # ========== Методы получения факультетов и программ ==========
    
    async def get_divisions(self) -> list[dict]:
        """
        Получение списка факультетов/подразделений.
        
        Returns:
            Список факультетов с полями: Alias, Name, Oid
        """
        return await self._request("/study/divisions")
    
    async def get_gsom_programs(self, level: str = "Bachelor") -> list[dict]:
        """
        Получение образовательных программ GSOM.
        
        Args:
            level: Уровень образования (Bachelor, Master, etc.)
        
        Returns:
            Список программ с полями: ProgramId, Name, AdmissionYears
        """
        # Сначала получаем программы по уровням для GSOM
        data = await self._request(f"/study/divisions/{config.GSOM_ALIAS}/programs/levels")
        
        programs = []
        for level_data in data:
            if level_data.get("StudyLevelName") == level:
                for program_combo in level_data.get("StudyProgramCombinations", []):
                    for admission_year in program_combo.get("AdmissionYears", []):
                        programs.append({
                            "ProgramId": admission_year.get("StudentGroupId"),
                            "Name": program_combo.get("Name"),
                            "Year": admission_year.get("YearNumber"),
                            "YearName": admission_year.get("YearName"),
                        })
        
        return programs
    
    async def get_groups_by_program(self, program_id: int) -> list[dict]:
        """
        Получение групп образовательной программы.
        
        Args:
            program_id: ID программы (StudentGroupId)
        
        Returns:
            Список групп с полями: StudentGroupId, StudentGroupName
        """
        data = await self._request(f"/groups/{program_id}/groups")
        
        groups = []
        if isinstance(data, dict) and "Groups" in data:
            for group in data.get("Groups", []):
                groups.append({
                    "StudentGroupId": group.get("StudentGroupId"),
                    "StudentGroupName": group.get("StudentGroupName"),
                })
        elif isinstance(data, list):
            for group in data:
                groups.append({
                    "StudentGroupId": group.get("StudentGroupId"),
                    "StudentGroupName": group.get("StudentGroupName"),
                })
        
        return groups
    
    async def get_bachelor_groups_by_year(self, year: int) -> list[dict]:
        """
        Получение групп бакалавриата GSOM по году поступления.
        
        Args:
            year: Год поступления
        
        Returns:
            Список групп
        """
        programs = await self.get_gsom_programs(level="Bachelor")
        
        all_groups = []
        for program in programs:
            if program.get("Year") == year:
                try:
                    groups = await self.get_groups_by_program(program["ProgramId"])
                    for group in groups:
                        group["ProgramName"] = program.get("Name", "")
                        all_groups.append(group)
                except SpbuApiError as e:
                    logger.warning(f"Failed to get groups for program {program['ProgramId']}: {e}")
                    continue
        
        return all_groups
    
    # ========== Методы получения расписания ==========
    
    async def get_group_events(
        self,
        group_id: int,
        from_date: date,
        to_date: date
    ) -> list[dict]:
        """
        Получение расписания группы за период.
        
        Args:
            group_id: ID группы
            from_date: Начало периода
            to_date: Конец периода
        
        Returns:
            Список событий (занятий)
        """
        from_str = format_date_for_api(from_date)
        to_str = format_date_for_api_end(to_date)
        
        endpoint = f"/groups/{group_id}/events/{from_str}/{to_str}"
        data = await self._request(endpoint)
        
        events = []
        
        # API возвращает данные сгруппированные по дням
        if isinstance(data, dict):
            for day in data.get("Days", []):
                day_date = day.get("Day", "")
                for event in day.get("DayStudyEvents", []):
                    event["DayDate"] = day_date
                    events.append(event)
        elif isinstance(data, list):
            # Если API вернул плоский список
            events = data
        
        return events
    
    async def get_group_schedule_today(self, group_id: int) -> list[dict]:
        """Получение расписания на сегодня."""
        from utils.datetime_utils import today
        t = today()
        return await self.get_group_events(group_id, t, t)
    
    async def get_group_schedule_tomorrow(self, group_id: int) -> list[dict]:
        """Получение расписания на завтра."""
        from datetime import timedelta
        from utils.datetime_utils import today
        t = today() + timedelta(days=1)
        return await self.get_group_events(group_id, t, t)
    
    async def get_group_schedule_week(self, group_id: int) -> list[dict]:
        """Получение расписания на неделю (7 дней начиная с сегодня)."""
        from datetime import timedelta
        from utils.datetime_utils import today
        start = today()
        end = start + timedelta(days=6)  # 7 дней включительно
        return await self.get_group_events(group_id, start, end)
    
    async def get_group_schedule_date(self, group_id: int, target_date: date) -> list[dict]:
        """Получение расписания на конкретную дату."""
        return await self.get_group_events(group_id, target_date, target_date)
    
    async def get_group_schedule_regular(self, group_id: int) -> list[dict]:
        """
        Получение регулярного расписания (today + 14 дней).
        Используется для отслеживания изменений.
        """
        from datetime import timedelta
        from utils.datetime_utils import today
        start = today()
        end = start + timedelta(days=config.REGULAR_SCHEDULE_DAYS)
        return await self.get_group_events(group_id, start, end)
    
    async def get_group_session_schedule(self, group_id: int) -> list[dict]:
        """
        Получение расписания сессии (today + 90 дней).
        Фильтрует только события типа: зачёт, экзамен, показ работ.
        """
        from datetime import timedelta
        from utils.datetime_utils import today
        
        start = today()
        end = start + timedelta(days=config.SESSION_SCHEDULE_DAYS)
        
        events = await self.get_group_events(group_id, start, end)
        
        # Фильтрация сессионных событий
        session_keywords = [
            "зачет", "зачёт",
            "экзамен",
            "показ работ",
            "credit", "exam",
        ]
        
        session_events = []
        for event in events:
            # Проверка по типу
            event_type = (event.get("Kind") or "").lower()
            subject = (event.get("Subject") or "").lower()
            
            is_session = False
            
            # Проверка типа события
            for keyword in session_keywords:
                if keyword in event_type or keyword in subject:
                    is_session = True
                    break
            
            if is_session:
                session_events.append(event)
        
        return session_events
    
    async def check_api_health(self) -> bool:
        """Проверка доступности API."""
        try:
            await self.get_divisions()
            return True
        except SpbuApiError:
            return False
