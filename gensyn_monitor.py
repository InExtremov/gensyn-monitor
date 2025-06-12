#!/usr/bin/env python3
"""
Gensyn Peers Monitor with Telegram Notifications
Мониторинг пиров Gensyn с уведомлениями в Telegram при потере связи
"""

import asyncio
import json
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Set, Any
import aiohttp
import configparser
from dataclasses import dataclass


@dataclass
class PeerStatus:
    """Статус пира"""
    peer_id: str
    score: Optional[float]
    reward: Optional[float]
    is_online: bool
    last_seen: datetime
    error_message: Optional[str] = None


class TelegramNotifier:
    """Класс для отправки уведомлений в Telegram"""
    
    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{bot_token}"
        
    async def send_message(self, message: str) -> bool:
        """Отправка сообщения в Telegram"""
        url = f"{self.base_url}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": "HTML"
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload) as response:
                    if response.status == 200:
                        logging.info("Telegram сообщение отправлено успешно")
                        return True
                    else:
                        logging.error(f"Ошибка отправки Telegram: {response.status}")
                        return False
        except Exception as e:
            logging.error(f"Ошибка при отправке в Telegram: {e}")
            return False


class GensynMonitor:
    """Основной класс мониторинга пиров Gensyn"""
    
    def __init__(self, config_path: str = "config.ini"):
        self.config = self._load_config(config_path)
        self.telegram = TelegramNotifier(
            self.config['telegram']['bot_token'],
            self.config['telegram']['chat_id']
        )
        
        # Настройки API
        self.url_base = "https://dashboard-math.gensyn.ai/api/v1/peer?id={}"
        self.timeout = int(self.config['monitoring']['timeout'])
        self.check_interval = int(self.config['monitoring']['check_interval'])
        self.max_retries = int(self.config['monitoring']['max_retries'])
        
        # Состояние мониторинга
        self.peer_statuses: Dict[str, PeerStatus] = {}
        self.offline_peers: Set[str] = set()
        self.last_status_report = datetime.now()
        
        # Настройка логирования
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('gensyn_monitor.log'),
                logging.StreamHandler()
            ]
        )
        
    def _load_config(self, config_path: str) -> configparser.ConfigParser:
        """Загрузка конфигурации"""
        config = configparser.ConfigParser()
        
        if not Path(config_path).exists():
            self._create_default_config(config_path)
            
        config.read(config_path)
        return config
    
    def _create_default_config(self, config_path: str):
        """Создание конфигурационного файла по умолчанию"""
        config = configparser.ConfigParser()
        
        config['telegram'] = {
            'bot_token': 'YOUR_BOT_TOKEN_HERE',
            'chat_id': 'YOUR_CHAT_ID_HERE'
        }
        
        config['monitoring'] = {
            'check_interval': '300',  # 5 минут
            'timeout': '10',
            'max_retries': '3',
            'status_report_interval': '3600'  # 1 час
        }
        
        config['peers'] = {
            'file_path': 'peers.txt'
        }
        
        with open(config_path, 'w') as f:
            config.write(f)
            
        logging.info(f"Создан конфигурационный файл: {config_path}")
        logging.warning("Не забудьте настроить Telegram bot_token и chat_id!")
    
    def load_peer_ids(self) -> List[str]:
        """Загрузка списка пиров из файла"""
        file_path = Path(self.config['peers']['file_path'])
        
        if not file_path.exists():
            logging.error(f"Файл с пирами не найден: {file_path}")
            return []
            
        with file_path.open(encoding="utf-8") as fh:
            peer_ids = [
                line.strip()
                for line in fh
                if line.strip() and not line.lstrip().startswith("#")
            ]
            
        logging.info(f"Загружено {len(peer_ids)} пиров для мониторинга")
        return peer_ids
    
    async def fetch_peer_status(self, session: aiohttp.ClientSession, peer_id: str) -> PeerStatus:
        """Получение статуса пира"""
        url = self.url_base.format(peer_id)
        
        for attempt in range(1, self.max_retries + 1):
            try:
                async with session.get(url, timeout=self.timeout) as response:
                    if response.status == 200:
                        data = await response.json()
                        return PeerStatus(
                            peer_id=peer_id,
                            score=data.get("score"),
                            reward=data.get("reward"),
                            is_online=True,
                            last_seen=datetime.now()
                        )
                    else:
                        error_msg = f"HTTP {response.status}"
                        if attempt == self.max_retries:
                            return PeerStatus(
                                peer_id=peer_id,
                                score=None,
                                reward=None,
                                is_online=False,
                                last_seen=datetime.now(),
                                error_message=error_msg
                            )
                        
            except Exception as e:
                error_msg = str(e)
                if attempt == self.max_retries:
                    return PeerStatus(
                        peer_id=peer_id,
                        score=None,
                        reward=None,
                        is_online=False,
                        last_seen=datetime.now(),
                        error_message=error_msg
                    )
                    
                await asyncio.sleep(2 ** attempt)  # Exponential backoff
                
        return PeerStatus(
            peer_id=peer_id,
            score=None,
            reward=None,
            is_online=False,
            last_seen=datetime.now(),
            error_message="Неизвестная ошибка"
        )
    
    async def check_all_peers(self) -> List[PeerStatus]:
        """Проверка всех пиров"""
        peer_ids = self.load_peer_ids()
        
        if not peer_ids:
            logging.warning("Нет пиров для проверки")
            return []
        
        async with aiohttp.ClientSession() as session:
            tasks = [self.fetch_peer_status(session, peer_id) for peer_id in peer_ids]
            statuses = await asyncio.gather(*tasks)
            
        return statuses
    
    async def process_status_changes(self, statuses: List[PeerStatus]):
        """Обработка изменений статуса пиров"""
        current_offline = set()
        new_offline = []
        recovered_peers = []
        
        for status in statuses:
            peer_id = status.peer_id
            
            # Обновляем текущий статус
            self.peer_statuses[peer_id] = status
            
            if not status.is_online:
                current_offline.add(peer_id)
                
                # Проверяем, не был ли пир офлайн ранее
                if peer_id not in self.offline_peers:
                    new_offline.append(status)
            else:
                # Проверяем, восстановился ли пир
                if peer_id in self.offline_peers:
                    recovered_peers.append(status)
        
        # Обновляем список офлайн пиров
        self.offline_peers = current_offline
        
        # Отправляем уведомления о новых проблемах
        if new_offline:
            await self._send_offline_notifications(new_offline)
        
        # Отправляем уведомления о восстановлении
        if recovered_peers:
            await self._send_recovery_notifications(recovered_peers)
    
    async def _send_offline_notifications(self, offline_statuses: List[PeerStatus]):
        """Отправка уведомлений о потере пиров"""
        if len(offline_statuses) == 1:
            status = offline_statuses[0]
            message = (
                f"🔴 <b>ПРОПАЛ ПИР GENSYN</b>\n\n"
                f"<b>Peer ID:</b> <code>{status.peer_id}</code>\n"
                f"<b>Время:</b> {status.last_seen.strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"<b>Ошибка:</b> {status.error_message or 'Недоступен'}"
            )
        else:
            message = f"🔴 <b>ПРОПАЛО {len(offline_statuses)} ПИРОВ GENSYN</b>\n\n"
            for status in offline_statuses:
                message += f"• <code>{status.peer_id}</code> - {status.error_message or 'Недоступен'}\n"
            message += f"\n<b>Время:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        
        await self.telegram.send_message(message)
        logging.warning(f"Отправлено уведомление о {len(offline_statuses)} офлайн пирах")
    
    async def _send_recovery_notifications(self, recovered_statuses: List[PeerStatus]):
        """Отправка уведомлений о восстановлении пиров"""
        if len(recovered_statuses) == 1:
            status = recovered_statuses[0]
            message = (
                f"✅ <b>ПИР GENSYN ВОССТАНОВЛЕН</b>\n\n"
                f"<b>Peer ID:</b> <code>{status.peer_id}</code>\n"
                f"<b>Score:</b> {status.score or '—'}\n"
                f"<b>Reward:</b> {status.reward or '—'}\n"
                f"<b>Время:</b> {status.last_seen.strftime('%Y-%m-%d %H:%M:%S')}"
            )
        else:
            message = f"✅ <b>ВОССТАНОВЛЕНО {len(recovered_statuses)} ПИРОВ GENSYN</b>\n\n"
            for status in recovered_statuses:
                message += f"• <code>{status.peer_id}</code>\n"
            message += f"\n<b>Время:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        
        await self.telegram.send_message(message)
        logging.info(f"Отправлено уведомление о восстановлении {len(recovered_statuses)} пиров")
    
    async def send_status_report(self):
        """Отправка периодического отчета о статусе"""
        if not self.peer_statuses:
            return
        
        online_count = sum(1 for status in self.peer_statuses.values() if status.is_online)
        offline_count = len(self.peer_statuses) - online_count
        
        message = (
            f"📊 <b>ОТЧЕТ О МОНИТОРИНГЕ GENSYN</b>\n\n"
            f"<b>Всего пиров:</b> {len(self.peer_statuses)}\n"
            f"<b>Онлайн:</b> ✅ {online_count}\n"
            f"<b>Офлайн:</b> ❌ {offline_count}\n"
            f"<b>Время отчета:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        
        if offline_count > 0:
            message += "\n\n<b>Офлайн пиры:</b>\n"
            for peer_id in self.offline_peers:
                status = self.peer_statuses.get(peer_id)
                if status:
                    message += f"• <code>{peer_id}</code> - {status.error_message or 'Недоступен'}\n"
        
        await self.telegram.send_message(message)
        logging.info("Отправлен периодический отчет")
    
    async def run_monitoring(self):
        """Основной цикл мониторинга"""
        logging.info("Запуск мониторинга пиров Gensyn...")
        
        # Отправляем стартовое сообщение
        await self.telegram.send_message(
            "🚀 <b>GENSYN MONITOR ЗАПУЩЕН</b>\n\n"
            f"Интервал проверки: {self.check_interval} секунд\n"
            f"Время запуска: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        
        status_report_interval = int(self.config['monitoring']['status_report_interval'])
        
        while True:
            try:
                # Проверяем все пиры
                statuses = await self.check_all_peers()
                
                if statuses:
                    await self.process_status_changes(statuses)
                    
                    # Отправляем периодический отчет
                    if (datetime.now() - self.last_status_report).total_seconds() >= status_report_interval:
                        await self.send_status_report()
                        self.last_status_report = datetime.now()
                
                # Логируем статистику
                online = sum(1 for s in statuses if s.is_online)
                offline = len(statuses) - online
                logging.info(f"Проверка завершена. Онлайн: {online}, Офлайн: {offline}")
                
            except Exception as e:
                logging.error(f"Ошибка в цикле мониторинга: {e}")
                await self.telegram.send_message(
                    f"⚠️ <b>ОШИБКА МОНИТОРИНГА</b>\n\n"
                    f"<code>{str(e)}</code>\n"
                    f"Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                )
            
            # Ждем следующую проверку
            await asyncio.sleep(self.check_interval)


async def main():
    """Главная функция"""
    monitor = GensynMonitor()
    
    try:
        await monitor.run_monitoring()
    except KeyboardInterrupt:
        logging.info("Мониторинг остановлен пользователем")
        await monitor.telegram.send_message(
            "⏹️ <b>GENSYN MONITOR ОСТАНОВЛЕН</b>\n\n"
            f"Время остановки: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
    except Exception as e:
        logging.error(f"Критическая ошибка: {e}")
        await monitor.telegram.send_message(
            f"💥 <b>КРИТИЧЕСКАЯ ОШИБКА МОНИТОРА</b>\n\n"
            f"<code>{str(e)}</code>\n"
            f"Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )


if __name__ == "__main__":
    asyncio.run(main())
