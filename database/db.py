"""
Модуль работы с базой данных SQLite.
Хранит: пользователей, группы, снимки расписания, отправленные уведомления.
"""

import aiosqlite
import json
import hashlib
from pathlib import Path
from typing import Any

from config import config


class Database:
    """Асинхронный класс для работы с SQLite."""
    
    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or config.DATABASE_PATH
        self._connection: aiosqlite.Connection | None = None
    
    async def connect(self) -> None:
        """Установка соединения с базой данных."""
        # Создаём директорию если не существует
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        
        self._connection = await aiosqlite.connect(self.db_path)
        self._connection.row_factory = aiosqlite.Row
        await self._create_tables()
    
    async def close(self) -> None:
        """Закрытие соединения."""
        if self._connection:
            await self._connection.close()
            self._connection = None
    
    @property
    def conn(self) -> aiosqlite.Connection:
        """Получение соединения с проверкой."""
        if not self._connection:
            raise RuntimeError("Database not connected")
        return self._connection
    
    async def _create_tables(self) -> None:
        """Создание таблиц базы данных."""
        await self.conn.executescript("""
            -- Пользователи
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                group_id INTEGER,
                group_name TEXT,
                notifications_enabled INTEGER DEFAULT 1,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            
            -- Снимки расписания для отслеживания изменений
            CREATE TABLE IF NOT EXISTS schedule_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id INTEGER NOT NULL,
                schedule_hash TEXT NOT NULL,
                schedule_data TEXT NOT NULL,
                snapshot_type TEXT DEFAULT 'regular',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(group_id, snapshot_type)
            );
            
            -- Отправленные уведомления (для предотвращения дублей)
            CREATE TABLE IF NOT EXISTS sent_notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                notification_hash TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, notification_hash)
            );
            
            -- Системное состояние
            CREATE TABLE IF NOT EXISTS system_state (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            
            -- Индексы
            CREATE INDEX IF NOT EXISTS idx_users_group_id ON users(group_id);
            CREATE INDEX IF NOT EXISTS idx_users_notifications ON users(notifications_enabled);
            CREATE INDEX IF NOT EXISTS idx_snapshots_group ON schedule_snapshots(group_id);
            CREATE INDEX IF NOT EXISTS idx_notifications_user ON sent_notifications(user_id);
            CREATE INDEX IF NOT EXISTS idx_notifications_hash ON sent_notifications(notification_hash);
            
            -- Композитный индекс для быстрой проверки дубликатов
            CREATE INDEX IF NOT EXISTS idx_notifications_user_hash ON sent_notifications(user_id, notification_hash);
        """)
        await self.conn.commit()
    
    # ========== Операции с пользователями ==========
    
    async def get_user(self, user_id: int) -> dict | None:
        """Получение пользователя по ID."""
        cursor = await self.conn.execute(
            "SELECT * FROM users WHERE user_id = ?",
            (user_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None
    
    async def create_or_update_user(
        self,
        user_id: int,
        group_id: int | None = None,
        group_name: str | None = None,
        notifications_enabled: bool | None = None
    ) -> None:
        """Создание или обновление пользователя."""
        user = await self.get_user(user_id)
        
        if user is None:
            # Создание нового пользователя
            await self.conn.execute(
                """INSERT INTO users (user_id, group_id, group_name, notifications_enabled)
                   VALUES (?, ?, ?, ?)""",
                (user_id, group_id, group_name, 1 if notifications_enabled is None else int(notifications_enabled))
            )
        else:
            # Обновление существующего
            updates = []
            params = []
            
            if group_id is not None:
                updates.append("group_id = ?")
                params.append(group_id)
            
            if group_name is not None:
                updates.append("group_name = ?")
                params.append(group_name)
            
            if notifications_enabled is not None:
                updates.append("notifications_enabled = ?")
                params.append(int(notifications_enabled))
            
            if updates:
                updates.append("updated_at = CURRENT_TIMESTAMP")
                params.append(user_id)
                
                await self.conn.execute(
                    f"UPDATE users SET {', '.join(updates)} WHERE user_id = ?",
                    tuple(params)
                )
        
        await self.conn.commit()
    
    async def set_user_group(self, user_id: int, group_id: int, group_name: str) -> None:
        """Установка группы пользователя."""
        await self.create_or_update_user(user_id, group_id=group_id, group_name=group_name)
    
    async def toggle_notifications(self, user_id: int) -> bool:
        """
        Переключение уведомлений пользователя.
        Возвращает новое состояние.
        """
        user = await self.get_user(user_id)
        if not user:
            return False
        
        new_state = not bool(user["notifications_enabled"])
        await self.create_or_update_user(user_id, notifications_enabled=new_state)
        return new_state
    
    async def get_users_by_group(self, group_id: int, notifications_only: bool = True) -> list[dict]:
        """Получение пользователей определённой группы."""
        if notifications_only:
            cursor = await self.conn.execute(
                "SELECT * FROM users WHERE group_id = ? AND notifications_enabled = 1",
                (group_id,)
            )
        else:
            cursor = await self.conn.execute(
                "SELECT * FROM users WHERE group_id = ?",
                (group_id,)
            )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    
    async def get_all_unique_groups(self) -> list[int]:
        """Получение списка всех уникальных групп."""
        cursor = await self.conn.execute(
            "SELECT DISTINCT group_id FROM users WHERE group_id IS NOT NULL"
        )
        rows = await cursor.fetchall()
        return [row["group_id"] for row in rows]
    
    # ========== Операции со снимками расписания ==========
    
    @staticmethod
    def _hash_schedule(schedule_data: list[dict]) -> str:
        """Вычисление хеша расписания."""
        # Сортируем для стабильного хеша
        serialized = json.dumps(schedule_data, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(serialized.encode()).hexdigest()
    
    async def get_schedule_snapshot(
        self,
        group_id: int,
        snapshot_type: str = "regular"
    ) -> tuple[str | None, list[dict] | None]:
        """
        Получение снимка расписания.
        Возвращает (hash, data) или (None, None).
        """
        cursor = await self.conn.execute(
            "SELECT schedule_hash, schedule_data FROM schedule_snapshots WHERE group_id = ? AND snapshot_type = ?",
            (group_id, snapshot_type)
        )
        row = await cursor.fetchone()
        
        if not row:
            return None, None
        
        return row["schedule_hash"], json.loads(row["schedule_data"])
    
    async def save_schedule_snapshot(
        self,
        group_id: int,
        schedule_data: list[dict],
        snapshot_type: str = "regular"
    ) -> str:
        """
        Сохранение снимка расписания.
        Возвращает хеш нового снимка.
        """
        schedule_hash = self._hash_schedule(schedule_data)
        serialized = json.dumps(schedule_data, ensure_ascii=False)
        
        await self.conn.execute(
            """INSERT INTO schedule_snapshots (group_id, schedule_hash, schedule_data, snapshot_type, created_at)
               VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(group_id, snapshot_type) DO UPDATE SET
                   schedule_hash = excluded.schedule_hash,
                   schedule_data = excluded.schedule_data,
                   created_at = CURRENT_TIMESTAMP""",
            (group_id, schedule_hash, serialized, snapshot_type)
        )
        await self.conn.commit()
        
        return schedule_hash
    
    # ========== Операции с уведомлениями ==========
    
    @staticmethod
    def _hash_notification(user_id: int, notification_data: dict) -> str:
        """Вычисление хеша уведомления."""
        data = {
            "user_id": user_id,
            **notification_data
        }
        serialized = json.dumps(data, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(serialized.encode()).hexdigest()
    
    async def is_notification_sent(self, user_id: int, notification_data: dict) -> bool:
        """Проверка, было ли уведомление отправлено."""
        notification_hash = self._hash_notification(user_id, notification_data)
        
        cursor = await self.conn.execute(
            "SELECT 1 FROM sent_notifications WHERE user_id = ? AND notification_hash = ?",
            (user_id, notification_hash)
        )
        return await cursor.fetchone() is not None
    
    async def mark_notification_sent(self, user_id: int, notification_data: dict) -> None:
        """Отметка уведомления как отправленного."""
        notification_hash = self._hash_notification(user_id, notification_data)
        
        await self.conn.execute(
            """INSERT OR IGNORE INTO sent_notifications (user_id, notification_hash)
               VALUES (?, ?)""",
            (user_id, notification_hash)
        )
        await self.conn.commit()
    
    async def cleanup_old_notifications(self, days: int = 30) -> int:
        """
        Очистка старых записей об уведомлениях.
        Возвращает количество удалённых записей.
        """
        cursor = await self.conn.execute(
            """DELETE FROM sent_notifications 
               WHERE created_at < datetime('now', ?)""",
            (f"-{days} days",)
        )
        await self.conn.commit()
        return cursor.rowcount
    
    # ========== Системное состояние ==========
    
    async def get_system_state(self, key: str) -> str | None:
        """Получение значения системного состояния."""
        cursor = await self.conn.execute(
            "SELECT value FROM system_state WHERE key = ?",
            (key,)
        )
        row = await cursor.fetchone()
        return row["value"] if row else None
    
    async def set_system_state(self, key: str, value: str) -> None:
        """Установка значения системного состояния."""
        await self.conn.execute(
            """INSERT INTO system_state (key, value, updated_at)
               VALUES (?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(key) DO UPDATE SET
                   value = excluded.value,
                   updated_at = CURRENT_TIMESTAMP""",
            (key, value)
        )
        await self.conn.commit()
    
    async def get_stats(self) -> dict:
        """Получение статистики для админки."""
        stats = {}
        
        # Количество пользователей
        cursor = await self.conn.execute("SELECT COUNT(*) as cnt FROM users")
        row = await cursor.fetchone()
        stats["total_users"] = row["cnt"]
        
        # Пользователи с группами
        cursor = await self.conn.execute(
            "SELECT COUNT(*) as cnt FROM users WHERE group_id IS NOT NULL"
        )
        row = await cursor.fetchone()
        stats["users_with_groups"] = row["cnt"]
        
        # Уведомления включены
        cursor = await self.conn.execute(
            "SELECT COUNT(*) as cnt FROM users WHERE notifications_enabled = 1"
        )
        row = await cursor.fetchone()
        stats["notifications_enabled"] = row["cnt"]
        
        # Уникальные группы
        cursor = await self.conn.execute(
            "SELECT COUNT(DISTINCT group_id) as cnt FROM users WHERE group_id IS NOT NULL"
        )
        row = await cursor.fetchone()
        stats["unique_groups"] = row["cnt"]
        
        # Системное состояние
        stats["last_schedule_check"] = await self.get_system_state("last_schedule_check")
        stats["last_session_check"] = await self.get_system_state("last_session_check")
        stats["last_error"] = await self.get_system_state("last_error")
        
        return stats
