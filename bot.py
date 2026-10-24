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


def get_numbered_list():
    """Список персонажей, отсортированный по алфавиту; каждому присвоен номер (1..N)."""
    ensure_cache()
    ordered = sorted(characters_cache.values(), key=lambda x: x.get("name", "").lower())
    return ordered


def search_character(q):
    """Ищет персонажа по имени, позывному, номеру в /list или названию темы."""
    ensure_cache()
    ql = q.lower().strip()
    # 1) Точное совпадение по имени
    for c in characters_cache.values():
        if c.get("name", "").lower() == ql:
            return c
    # 2) Точное совпадение по позывному
    for c in characters_cache.values():
        if c.get("moniker", "").lower() == ql:
            return c
    # 3) Номер из списка /list (например "7" или "#7")
    num_m = re.fullmatch(r"#?(\d+)", ql)
    if num_m:
        ordered = get_numbered_list()
        idx = int(num_m.group(1))
        if 1 <= idx <= len(ordered):
            return ordered[idx - 1]
    # 4) Частичное совпадение по имени
    for c in characters_cache.values():
        if ql in c.get("name", "").lower():
            return c
    # 5) Частичное совпадение по позывному
    for c in characters_cache.values():
        if ql in c.get("moniker", "").lower():
            return c
    # 6) Частичное совпадение по названию темы
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
