# Gensyn Peers Monitor

Мониторинг пиров Gensyn с уведомлениями в Telegram при потере связи.

## Установка

1. Создайте виртуальное окружение:
```bash
python3.10 -m venv venv
source venv/bin/activate
```

2. Установите зависимости:
```bash
pip install -r requirements.txt
```

3. Настройте Telegram бота:
   - Создайте бота через @BotFather
   - Получите bot_token
   - Получите chat_id (можно через @userinfobot)

4. Отредактируйте `config.ini`:
   - Вставьте ваш bot_token
   - Вставьте ваш chat_id

5. Добавьте peer ID в `peers.txt` (по одному на строку)

## Запуск

```bash
python3 gensyn_monitor.py
```

## Функции

- ✅ Постоянный мониторинг пиров
- 🔴 Уведомления о потере пиров
- ✅ Уведомления о восстановлении
- 📊 Периодические отчеты
- 📝 Логирование в файл
