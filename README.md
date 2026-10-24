# RWRD Character Bot

Telegram-бот для парсинга анкет персонажей с форума [Cyberpunk: Rewired](https://rwrd.rusff.me/viewforum.php?id=25).

## Команды бота

| Команда | Описание |
|---------|----------|
| `/char Имя` | Найти анкету персонажа (по имени, позывному или названию темы) |
| `/list` | Список всех персонажей |
| `/atem` | Активные темы форума |
| `/help` | Справка |

## Установка и запуск

```bash
pip install -r requirements.txt

# токен задаётся через переменную окружения (не хранится в коде)
export BOT_TOKEN="123456:ABC-your-token"
python bot.py
