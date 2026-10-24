#!/usr/bin/env python3
"""
Telegram-бот для парсинга анкет персонажей с форума Cyberpunk: Rewired
Форум: https://rwrd.rusff.me/viewforum.php?id=25
Команда: /Char "Имя персонажа"
"""

import os
import re
import time
import logging
import requests
from bs4 import BeautifulSoup
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# ======================== НАСТРОЙКИ ========================
# Токен лучше задавать через переменную окружения BOT_TOKEN,
# а не хранить прямо в коде.
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
FORUM_URL = "https://rwrd.rusff.me"
FORUM_ID = 25
CACHE_TTL = 3600
MAX_PAGES = 25
REQUEST_TIMEOUT = 15
REQUEST_DELAY = 0.5

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
}

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

characters_cache = {}
last_update = 0


def get_forum_topics():
    topics = []
    page = 1
    while page <= MAX_PAGES:
        url = f"{FORUM_URL}/viewforum.php?id={FORUM_ID}"
        if page > 1:
            url += f"&p={page}"
        logger.info(f"Загрузка страницы {page}: {url}")
        try:
            response = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
        except requests.RequestException as e:
            logger.error(f"Ошибка загрузки страницы {page}: {e}")
            break
        soup = BeautifulSoup(response.text, "html.parser")
        topic_table = soup.find("table", attrs={"summary": re.compile(r"Список тем")})
        if not topic_table:
            forum_div = soup.find("div", class_="forum")
            if forum_div:
                topic_table = forum_div.find("table")
        if not topic_table:
            all_links = soup.find_all("a", href=re.compile(r"viewtopic\.php\?id=\d+"))
            for link in all_links:
                href = link.get("href", "")
                if "#p" in href:
                    continue
                m = re.search(r"id=(\d+)", href)
                if m:
                    tid = m.group(1)
                    title = link.get_text(strip=True)
                    if len(title) < 3:
                        continue
                    ym = re.search(r'\[(\d{4}(?:\s*/\s*\d{4})?)\]', title)
                    year = ym.group(1) if ym else ""
                    tc = re.sub(r'^\[\d{4}(?:\s*/\s*\d{4})?\]\s*', '', title)
                    tc = re.sub(r'\s*\[\d{4}(?:\s*/\s*\d{4})?\]$', '', tc)
                    if any(t["id"] == tid for t in topics):
                        continue
                    topics.append({"id": tid, "title": tc, "title_full": title, "author": "Unknown", "year": year, "url": f"{FORUM_URL}/viewtopic.php?id={tid}"})
            if topics:
                break
            else:
                break
        rows = topic_table.find_all("tr")
        found = False
        for row in rows:
            link = row.find("a", href=re.compile(r"viewtopic\.php\?id=\d+"))
            if link:
                href = link.get("href", "")
                if "#p" in href:
                    continue
                m = re.search(r"id=(\d+)", href)
                if m:
                    tid = m.group(1)
                    title = link.get_text(strip=True)
                    if len(title) < 3:
                        continue
                    au = row.find("span", class_="byuser-username")
                    author = au.get_text(strip=True) if au else "Unknown"
                    ym = re.search(r'\[(\d{4}(?:\s*/\s*\d{4})?)\]', title)
                    year = ym.group(1) if ym else ""
                    tc = re.sub(r'^\[\d{4}(?:\s*/\s*\d{4})?\]\s*', '', title)
                    tc = re.sub(r'\s*\[\d{4}(?:\s*/\s*\d{4})?\]$', '', tc)
                    topics.append({"id": tid, "title": tc, "title_full": title, "author": author, "year": year, "url": f"{FORUM_URL}/viewtopic.php?id={tid}"})
                    found = True
        if not found:
            break
        if not soup.find("a", class_="next"):
            break
        time.sleep(REQUEST_DELAY)
        page += 1
    logger.info(f"Всего найдено тем: {len(topics)}")
    return topics


def parse_character_sheet(topic_url):
    try:
        response = requests.get(topic_url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
    except requests.RequestException as e:
        logger.error(f"Ошибка загрузки темы {topic_url}: {e}")
        return None
    soup = BeautifulSoup(response.text, "html.parser")
    pc = soup.find("div", class_="post-content")
    if not pc:
        pc = soup.find("div", class_="postmsg")
    if not pc:
        pc = soup.find("div", class_="blockpost")
    if not pc:
        return None
    ch = {}
    pt = pc.get_text(separator="\n", strip=True)
    nt = pc.find("div", class_="custom_tag_name")
    if nt:
        ch["name"] = nt.get_text(strip=True)
    else:
        for line in pt.split("\n")[:10]:
            line = line.strip()
            if line and 2 < len(line) < 50 and not line.startswith(("http", "Автор:", "Участник", "Новичок", "Активный")):
                if any(s in line for s in ["Сообщений", "Уважение", "Провел на форуме", "Последний визит", "Активен", "2077", "2099"]):
                    continue
                ch["name"] = line
                break
    mt = pc.find("div", class_="custom_tag_moniker")
    if mt:
        ch["moniker"] = mt.get_text(strip=True)
    dt = pc.find("div", class_="custom_tag_dob")
    if dt:
        ch["dob"] = dt.get_text(strip=True)
    else:
        dm = re.search(r'(\d{2}\.\d{2}\.\d{4})', pt)
        if dm:
            ch["dob"] = dm.group(1)
    ot = pc.find("div", class_="custom_tag_occupation")
    if ot:
        ch["occupation"] = ot.get_text(strip=True)
    lt = pc.find("div", class_="custom_tag_loyalty")
    if lt:
        ch["loyalty"] = lt.get_text(strip=True)
    i1 = pc.find("div", class_="custom_tag_info1")
    if i1:
        implants = []
        for li in i1.find_all("li"):
            t = li.get_text(strip=True)
            if t and not t.endswith(":") and len(t) > 1:
                implants.append(t)
        ch["implants"] = implants
    i2 = pc.find("div", class_="custom_tag_info2")
    if i2:
        skills = []
        for li in i2.find_all("li"):
            t = li.get_text(strip=True)
            if t:
                skills.append(t)
        ch["skills"] = skills
    at = pc.find("div", class_="custom_tag_anktxt")
    if at:
        for q in at.find_all(["div"], class_=re.compile(r"quote-box|spoiler-box")):
            q.decompose()
        # Удаляем встроенные стили/скрипты и BBCode-разметку [html]...[/html],
        # иначе их текст попадает в сообщение бота как мусор
        for tag in at.find_all(["style", "script"]):
            tag.decompose()
        bio_html = str(at)
        bio_html = re.sub(r"\[/?html\]", "", bio_html)
        clean_soup = BeautifulSoup(bio_html, "html.parser")
        ch["bio"] = clean_soup.get_text(separator="\n", strip=True)
    else:
        for q in pc.find_all("blockquote"):
            q.decompose()
        bio = pc.get_text(separator="\n", strip=True)
        bl = []
        for line in bio.split("\n"):
            if any(s in line for s in ["ДОПОЛНИТЕЛЬНО", "ПРИМЕР ПОСТА", "свернуть блок"]):
                break
            bl.append(line)
        bio = "\n".join(bl).strip()
        if len(bio) > 200:
            ch["bio"] = bio
    yt = pc.find("lzyear")
    if yt:
        ch["year"] = yt.get_text(strip=True)
    return ch


def update_characters_cache():
    global characters_cache, last_update
    logger.info("Обновление кэша персонажей...")
    topics = get_forum_topics()
    nc = {}
    if not topics:
        logger.error("Темы не найдены!")
        return
    for i, topic in enumerate(topics):
        logger.info(f"Парсинг темы {i+1}/{len(topics)}: {topic['title']}")
        cd = parse_character_sheet(topic["url"])
        if cd:
            nc[topic["id"]] = {**cd, "topic_id": topic["id"], "topic_url": topic["url"], "topic_title": topic["title_full"], "author": topic["author"]}
            if "name" not in nc[topic["id"]] or not nc[topic["id"]].get("name"):
                nc[topic["id"]]["name"] = topic["title"]
            if "year" not in nc[topic["id"]] and topic["year"]:
                nc[topic["id"]]["year"] = topic["year"]
        time.sleep(REQUEST_DELAY)
    characters_cache = nc
    last_update = time.time()
    logger.info(f"Кэш обновлён. Найдено персонажей: {len(characters_cache)}")


def ensure_cache():
    if not characters_cache or (time.time() - last_update) > CACHE_TTL:
        update_characters_cache()


def search_character(q):
    ensure_cache()
    ql = q.lower().strip()
    for c in characters_cache.values():
        if c.get("name", "").lower() == ql:
            return c
    for c in characters_cache.values():
        if ql in c.get("name", "").lower():
            return c
    for c in characters_cache.values():
        if ql in c.get("moniker", "").lower():
            return c
    for c in characters_cache.values():
        if ql in c.get("topic_title", "").lower():
            return c
    return None


def get_active_topics():
    url = f"{FORUM_URL}/search.php?action=show_recent"
    logger.info(f"Загрузка активных тем: {url}")
    try:
        response = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
    except requests.RequestException as e:
        logger.error(f"Ошибка загрузки активных тем: {e}")
        return []
    soup = BeautifulSoup(response.text, "html.parser")
    topic_table = soup.find("table", attrs={"summary": re.compile(r"Результаты поиска")})
    if not topic_table:
        logger.warning("Таблица активных тем не найдена")
        return []
    topics = []
    rows = topic_table.find_all("tr")
    for row in rows:
        if row.find("th"):
            continue
        tcl = row.find("td", class_="tcl")
        if not tcl:
            continue
        topic_link = tcl.find("a", href=re.compile(r"viewtopic\.php\?id=\d+"))
        if not topic_link:
            continue
        topic_title = topic_link.get_text(strip=True)
        topic_url = topic_link.get("href", "")
        tcr = row.find("td", class_="tcr")
        if not tcr:
            continue
        last_post_link = tcr.find("a", href=re.compile(r"viewtopic\.php\?id=\d+.*#p\d+"))
        if not last_post_link:
            continue
        last_post_url = last_post_link.get("href", "")
        last_post_time = last_post_link.get_text(strip=True)
        last_author_span = tcr.find("span", class_="byuser-username")
        last_author = last_author_span.get_text(strip=True) if last_author_span else ""
        topics.append({"title": topic_title, "topic_url": topic_url, "last_post_url": last_post_url, "last_post_time": last_post_time, "last_author": last_author})
    logger.info(f"Найдено активных тем: {len(topics)}")
    return topics


def split_message(text, max_len=4000):
    """Режет текст на части не длиннее max_len (учитывая переносы строк)."""
    if len(text) <= max_len:
        return [text]
    parts, cur = [], ""
    for line in text.split('\n'):
        # если одна строка длиннее лимита — режем её по символьным блокам
        while len(line) > max_len:
            if cur:
                parts.append(cur)
                cur = ""
            parts.append(line[:max_len])
            line = line[max_len:]
        if len(cur) + len(line) + 1 > max_len:
            if cur:
                parts.append(cur)
            cur = line + '\n'
        else:
            cur += line + '\n'
    if cur:
        parts.append(cur)
    return parts


def fmt(ch):
    if not ch:
        return None
    L = []
    n = ch.get('name', 'Неизвестно')
    L.append(f"📋 *{n}*")
    if ch.get("moniker") and ch["moniker"] != n:
        L.append(f"🏷 Позывной: _{ch['moniker']}_")
    if ch.get("dob") and ch["dob"] != "Неизвестно":
        L.append(f"📅 Дата рождения: {ch['dob']}")
    if ch.get("occupation") and ch["occupation"] != "Неизвестно":
        L.append(f"💼 Занятие: {ch['occupation']}")
    if ch.get("loyalty") and ch["loyalty"] != "Неизвестно":
        L.append(f"🤝 Лояльность: {ch['loyalty']}")
    if ch.get("year"):
        L.append(f"🕐 Таймлайн: {ch['year']}")
    if ch.get("implants") and len(ch["implants"]) > 0:
        L.append("")
        L.append("🦾 *Импланты:*")
        L.append(", ".join(ch["implants"]))
    if ch.get("skills") and len(ch["skills"]) > 0:
        L.append("")
        L.append("⚡ *Навыки:*")
        for s in ch["skills"]:
            L.append(f"• {s}")
    if ch.get("bio"):
        L.append("")
        L.append("📖 *Биография:*")
        L.append(ch["bio"])
    if ch.get("topic_url"):
        L.append("")
        L.append(f"🔗 [Открыть на форуме]({ch['topic_url']})")
    return "\n".join(L)


async def start_cmd(update, ctx):
    await update.message.reply_text(
        "Привет! Я бот-помощник участников CyberPunk Rewired. "
        "Если ты не ковбой, я всё тебе расскажу: "
        "Воспользуйся /help для получения списка команд"
    )


async def char_cmd(update, ctx):
    if not ctx.args:
        await update.message.reply_text("⚠️ Укажите имя. Пример: /char Leon Cross", parse_mode="Markdown")
        return
    q = " ".join(ctx.args).strip('"').strip("'").strip()
    if not q:
        await update.message.reply_text("⚠️ Имя не может быть пустым.")
        return
    sm = await update.message.reply_text(f"🔍 Ищу: *{q}*...\n_(может занять до 2 мин)_", parse_mode="Markdown")
    try:
        ch = search_character(q)
        if ch:
            msg = fmt(ch)
            parts = split_message(msg)
            await sm.edit_text(parts[0], parse_mode="Markdown", disable_web_page_preview=True)
            for p in parts[1:]:
                await update.message.reply_text(p, parse_mode="Markdown", disable_web_page_preview=True)
        else:
            await sm.edit_text(f"❌ Не найден: \"{q}\"\n\nЗагружено: {len(characters_cache)}\nИспользуйте /list", parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Search error: {e}")
        await sm.edit_text(f"⚠️ Ошибка. Загружено: {len(characters_cache)}")


async def list_cmd(update, ctx):
    sm = await update.message.reply_text("📋 Загружаю список...", parse_mode="Markdown")
    try:
        ensure_cache()
        if not characters_cache:
            await sm.edit_text("❌ Не удалось загрузить список.")
            return
        L = [f"📋 *Персонажи ({len(characters_cache)}):*\n"]
        for c in sorted(characters_cache.values(), key=lambda x: x.get("name", "").lower()):
            n = c.get("name", "?")
            y = c.get("year", "")
            line = f"• *{n}*"
            if y:
                line += f" [{y}]"
            L.append(line)
        msg = "\n".join(L)
        if len(msg) > 4000:
            parts, cur = [], ""
            for line in msg.split("\n"):
                if len(cur) + len(line) + 1 > 3900:
                    parts.append(cur)
                    cur = line + "\n"
                else:
                    cur += line + "\n"
            if cur:
                parts.append(cur)
            for i, p in enumerate(parts):
                if i == 0:
                    await sm.edit_text(p, parse_mode="Markdown")
                else:
                    await update.message.reply_text(p, parse_mode="Markdown")
        else:
            await sm.edit_text(msg, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"List error: {e}")
        await sm.edit_text(f"⚠️ Ошибка: {str(e)[:200]}")


async def atem_cmd(update, ctx):
    sm = await update.message.reply_text("🔍 Загружаю активные темы...")
    try:
        topics = get_active_topics()
        if not topics:
            await sm.edit_text("❌ Не удалось загрузить активные темы.")
            return
        L = [f"🔥 *Активные темы ({len(topics)}):*\n"]
        for i, t in enumerate(topics, 1):
            line = f"{i}. [{t['title']}]({t['last_post_url']})"
            if t["last_author"]:
                line += f"\n   └ {t['last_post_time']} — {t['last_author']}"
            else:
                line += f"\n   └ {t['last_post_time']}"
            L.append(line)
        msg = "\n\n".join(L)
        if len(msg) > 4000:
            parts, cur = [], ""
            for line in L:
                if len(cur) + len(line) + 2 > 3900:
                    parts.append(cur)
                    cur = line + "\n\n"
                else:
                    cur += line + "\n\n"
            if cur:
                parts.append(cur)
            for i, p in enumerate(parts):
                if i == 0:
                    await sm.edit_text(p, parse_mode="Markdown", disable_web_page_preview=True)
                else:
                    await update.message.reply_text(p, parse_mode="Markdown", disable_web_page_preview=True)
        else:
            await sm.edit_text(msg, parse_mode="Markdown", disable_web_page_preview=True)
    except Exception as e:
        logger.error(f"Atem error: {e}")
        await sm.edit_text(f"⚠️ Ошибка: {str(e)[:200]}")


async def help_cmd(update, ctx):
    await update.message.reply_text(
        "🤖 *Помощь*\n\n"
        "/char `Имя` — найти анкету\n"
        "/list — список персонажей\n"
        "/atem — активные темы\n"
        "/help — справка\n\n"
        "📌 https://rwrd.rusff.me/viewforum.php?id=25",
        parse_mode="Markdown",
    )


def main():
    if not BOT_TOKEN:
        raise SystemExit(
            "Ошибка: не задан токен бота.\n"
            "Получите токен у @BotFather и задайте его через переменную окружения:\n"
            '    export BOT_TOKEN="123456:ABC-DEF..."'
        )
    logger.info("=" * 50)
    logger.info("Запуск RWRD Character Bot...")
    logger.info(f"Форум: {FORUM_URL}/viewforum.php?id={FORUM_ID}")
    logger.info("=" * 50)
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("char", char_cmd))
    app.add_handler(CommandHandler("Char", char_cmd))
    app.add_handler(CommandHandler("CHAR", char_cmd))
    app.add_handler(CommandHandler("list", list_cmd))
    app.add_handler(CommandHandler("List", list_cmd))
    app.add_handler(CommandHandler("atem", atem_cmd))
    app.add_handler(CommandHandler("Atem", atem_cmd))
    app.add_handler(CommandHandler("ATEM", atem_cmd))
    logger.info("Бот запущен!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
