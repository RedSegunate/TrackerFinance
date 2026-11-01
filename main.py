"""
Личный финансовый Telegram-бот.
- Пишете "вода 50" в чат или диктуете через iPhone-команду -> бот сам выбирает категорию.
- Статистика, бюджеты по категориям, экспорт в Excel.
Только рубли.
"""
import asyncio
import hashlib
import hmac
import io
import json
import logging
import math
import os
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    BotCommand,
    BufferedInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    MenuButtonDefault,
    MenuButtonWebApp,
    Message,
    ReplyKeyboardMarkup,
    WebAppInfo,
)
from aiohttp import web
from openpyxl import Workbook

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("finance-bot")


def load_env(path: str = ".env") -> None:
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


load_env()

# ---------- Настройки (берутся из переменных окружения) ----------
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
if not BOT_TOKEN:
    raise SystemExit("Не задан BOT_TOKEN. Создайте бота у @BotFather и добавьте токен в .env или в Variables на Railway.")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")  # необязательно: без ключа бот работает по словарю
AI_ENABLED = os.getenv("AI_ENABLED", "0").strip().lower() in ("1", "true", "yes", "on")
DB_PATH = os.getenv("DB_PATH", "finance.db")
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
DB_SCHEMA = os.getenv("DB_SCHEMA", "tracker_finance").strip()
if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", DB_SCHEMA):
    raise SystemExit("DB_SCHEMA must be a lowercase PostgreSQL identifier")
PORT = int(os.getenv("PORT", "8080"))
PUBLIC_URL = os.getenv("PUBLIC_URL", "").rstrip("/")
TZ = ZoneInfo(os.getenv("TIMEZONE", "Europe/Moscow"))
MODEL = os.getenv("CLAUDE_MODEL", "claude-haiku-5-5")
# Пустой ALLOWED_USERS означает, что бот открыт всем пользователям Telegram.
ALLOWED_USERS = {int(x) for x in os.getenv("ALLOWED_USERS", "").replace(" ", "").split(",") if x}
ADMIN_USERS = {int(x) for x in os.getenv("ADMIN_USERS", "").replace(" ", "").split(",") if x}
APP_DEV = os.getenv("APP_DEV", "").lower() in ("1", "true", "yes")
WEBAPP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "webapp")
BOT_USERNAME = "financetrackertjk_bot"

EXPENSE_CATS = [
    "Продукты", "Кафе и рестораны", "Транспорт", "Авто", "Жильё", "Связь и интернет",
    "Здоровье", "Одежда", "Красота", "Развлечения", "Подписки", "Образование",
    "Семья и дети", "Подарки", "Путешествия", "Бизнес-расходы", "Другое",
]
INCOME_CATS = ["Зарплата", "Подработка", "Бизнес", "Подарок", "Другое"]

bot = Bot(BOT_TOKEN)
dp = Dispatcher()
pending_add: set[int] = set()
_pg_pool = None
if DATABASE_URL:
    try:
        from psycopg.rows import dict_row
        from psycopg_pool import ConnectionPool
    except ImportError as exc:
        raise SystemExit("DATABASE_URL is set, but psycopg is missing; install requirements.txt") from exc

claude = None
if AI_ENABLED and ANTHROPIC_API_KEY:
    from anthropic import AsyncAnthropic
    claude = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
elif AI_ENABLED:
    log.warning("AI_ENABLED is set, but ANTHROPIC_API_KEY is missing; using the local parser")


# ---------- База данных ----------
class PostgresConnection:
    def __init__(self, connection):
        self.connection = connection

    @staticmethod
    def _query(query: str) -> str:
        return query.replace("?", "%s")

    def execute(self, query: str, params=()):
        return self.connection.execute(self._query(query), params)

    def executemany(self, query: str, params):
        return self.connection.executemany(self._query(query), params)


def postgres_pool():
    global _pg_pool
    if _pg_pool is None:
        _pg_pool = ConnectionPool(
            conninfo=DATABASE_URL,
            min_size=1,
            max_size=max(2, int(os.getenv("DB_POOL_SIZE", "5"))),
            kwargs={"row_factory": dict_row, "prepare_threshold": None},
            open=False,
        )
        _pg_pool.open(wait=True)
    return _pg_pool


def close_postgres_pool():
    global _pg_pool
    if _pg_pool is not None:
        _pg_pool.close()
        _pg_pool = None


@contextmanager
def db():
    if DATABASE_URL:
        with postgres_pool().connection() as conn:
            conn.execute(f'SET LOCAL search_path TO "{DB_SCHEMA}"')
            yield PostgresConnection(conn)
        return

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    if DATABASE_URL:
        with postgres_pool().connection() as conn:
            conn.execute(f'CREATE SCHEMA IF NOT EXISTS "{DB_SCHEMA}"')
    else:
        os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    with db() as c:
        id_type = "BIGSERIAL PRIMARY KEY" if DATABASE_URL else "INTEGER PRIMARY KEY AUTOINCREMENT"
        user_id_type = "BIGINT" if DATABASE_URL else "INTEGER"
        amount_type = "DOUBLE PRECISION" if DATABASE_URL else "REAL"
        schema = f"""
            CREATE TABLE IF NOT EXISTS users (
                user_id {user_id_type} PRIMARY KEY,
                token TEXT UNIQUE NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS transactions (
                id {id_type},
                user_id {user_id_type} NOT NULL,
                kind TEXT NOT NULL,
                amount {amount_type} NOT NULL,
                category TEXT NOT NULL,
                note TEXT,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_tx_user_date ON transactions(user_id, created_at);
            CREATE TABLE IF NOT EXISTS budgets (
                user_id {user_id_type} NOT NULL,
                category TEXT NOT NULL,
                limit_amount {amount_type} NOT NULL,
                PRIMARY KEY (user_id, category)
            );
            CREATE TABLE IF NOT EXISTS goals (
                id {id_type},
                user_id {user_id_type} NOT NULL,
                title TEXT NOT NULL,
                target_amount {amount_type} NOT NULL,
                icon TEXT NOT NULL DEFAULT '🎯',
                saved_amount {amount_type} NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS user_settings (
                user_id {user_id_type} PRIMARY KEY,
                theme TEXT NOT NULL DEFAULT 'system',
                timezone TEXT NOT NULL DEFAULT 'Europe/Moscow',
                budget_notifications INTEGER NOT NULL DEFAULT 1,
                weekly_summary INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS deleted_transactions (
                tx_id {user_id_type} PRIMARY KEY,
                user_id {user_id_type} NOT NULL,
                kind TEXT NOT NULL,
                amount {amount_type} NOT NULL,
                category TEXT NOT NULL,
                note TEXT,
                created_at TEXT NOT NULL,
                deleted_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS budget_alerts (
                user_id {user_id_type} NOT NULL,
                category TEXT NOT NULL,
                month_key TEXT NOT NULL,
                level TEXT NOT NULL,
                sent_at TEXT NOT NULL,
                PRIMARY KEY (user_id, category, month_key, level)
            );
            CREATE TABLE IF NOT EXISTS weekly_reports (
                user_id {user_id_type} NOT NULL,
                week_key TEXT NOT NULL,
                sent_at TEXT NOT NULL,
                PRIMARY KEY (user_id, week_key)
            );
            CREATE TABLE IF NOT EXISTS rules (
                user_id {user_id_type} NOT NULL,
                word TEXT NOT NULL,
                category TEXT NOT NULL,
                PRIMARY KEY (user_id, word)
            );
        """
        for statement in schema.split(";"):
            if statement.strip():
                c.execute(statement)
        if DATABASE_URL:
            for table in (
                "users", "transactions", "budgets", "goals", "user_settings",
                "deleted_transactions", "budget_alerts", "weekly_reports", "rules",
            ):
                c.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
            goal_columns = {row["column_name"] for row in c.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema=current_schema() AND table_name='goals'"
            ).fetchall()}
            settings_columns = {row["column_name"] for row in c.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema=current_schema() AND table_name='user_settings'"
            ).fetchall()}
        else:
            goal_columns = {row["name"] for row in c.execute("PRAGMA table_info(goals)")}
            settings_columns = {row["name"] for row in c.execute("PRAGMA table_info(user_settings)")}
        if "icon" not in goal_columns:
            c.execute("ALTER TABLE goals ADD COLUMN icon TEXT NOT NULL DEFAULT '🎯'")
        if "timezone" not in settings_columns:
            c.execute("ALTER TABLE user_settings ADD COLUMN timezone TEXT NOT NULL DEFAULT 'Europe/Moscow'")


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_USERS


def allowed(user_id: int) -> bool:
    return user_id in ADMIN_USERS or not ALLOWED_USERS or user_id in ALLOWED_USERS


def ensure_user(user_id: int) -> str:
    with db() as c:
        row = c.execute("SELECT token FROM users WHERE user_id=?", (user_id,)).fetchone()
        if row:
            return row["token"]
        token = secrets.token_urlsafe(24)
        c.execute(
            "INSERT INTO users(user_id, token, created_at) VALUES (?,?,?)",
            (user_id, token, datetime.now(timezone.utc).isoformat()),
        )
        return token


def user_settings(user_id: int) -> dict:
    with db() as c:
        c.execute(
            "INSERT INTO user_settings(user_id,timezone) VALUES (?,?) ON CONFLICT(user_id) DO NOTHING",
            (user_id, str(TZ)),
        )
        row = c.execute("SELECT * FROM user_settings WHERE user_id=?", (user_id,)).fetchone()
    settings = dict(row)
    try:
        ZoneInfo(settings["timezone"])
    except Exception:
        settings["timezone"] = str(TZ)
    return settings


def user_timezone(user_id: int) -> ZoneInfo:
    return ZoneInfo(user_settings(user_id)["timezone"])


def user_by_token(token: str):
    if not token:
        return None
    with db() as c:
        row = c.execute("SELECT user_id FROM users WHERE token=?", (token,)).fetchone()
        return row["user_id"] if row else None


# ---------- Утилиты ----------
def money(x: float) -> str:
    s = f"{x:,.2f}" if abs(x - round(x)) > 0.004 else f"{x:,.0f}"
    return s.replace(",", " ") + " ₽"


def period_start(name: str, tz: ZoneInfo = TZ) -> str:
    now = datetime.now(tz)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if name == "today":
        start = midnight
    elif name == "week":
        start = midnight - timedelta(days=midnight.weekday())
    elif name == "year":
        start = midnight.replace(month=1, day=1)
    else:
        start = midnight.replace(day=1)
    return start.astimezone(timezone.utc).isoformat()


def local_dt(iso: str, tz: ZoneInfo = TZ) -> datetime:
    return datetime.fromisoformat(iso).astimezone(tz)


# ---------- Разбор текста через Claude ----------
SYSTEM_PROMPT = f"""Ты разбираешь короткие записи о личных финансах на русском языке.
Верни ТОЛЬКО JSON без пояснений и без markdown, в формате:
{{"items":[{{"kind":"expense|income","amount":число,"category":"...","note":"..."}}]}}

Правила:
- Валюта всегда рубли. "к" или "тыс" = тысяча (например "5к" = 5000).
- По умолчанию запись - расход (expense). Доход (income), если речь про зарплату, поступление, получил, пришло, заработал, перевели мне и т.п.
- В одном сообщении может быть несколько записей - верни каждую отдельным элементом.
- Категории расходов (выбери ровно одну из списка): {", ".join(EXPENSE_CATS)}.
- Категории доходов (выбери ровно одну из списка): {", ".join(INCOME_CATS)}.
- note - короткое название покупки или источника дохода (1-4 слова), с маленькой буквы.
- Если суммы нет или текст не про деньги, верни {{"items":[]}}.
"""


# ---------- Разбор без ИИ: словарь + выученные слова ----------
def norm(s: str) -> str:
    return s.lower().replace("ё", "е")


# "слово*" совпадает по началу слова, без "*" - только слово целиком
EXPENSE_KEYWORDS = {
    "Продукты": ["вода", "воду", "воды", "хлеб*", "молок*", "продукт*", "магазин*", "пятероч*", "магнит", "ашан*",
                 "яйц*", "яиц*", "мяс*", "курица", "курицу", "курицы", "овощ*", "фрукт*", "сыр*", "колбас*",
                 "сахар", "макарон*", "круп*", "рыб*", "масл*", "сок", "соки", "пиво", "вино", "чай", "конфет*",
                 "шоколад*", "йогурт*", "творог", "банан*", "яблок*", "картошк*", "лук", "помидор*", "огурц*",
                 "базар", "рынок", "супермаркет*"],
    "Кафе и рестораны": ["кафе", "ресторан*", "кофе", "обед*", "ужин*", "завтрак*", "пицц*", "бургер*", "суши",
                         "ролл*", "шаурм*", "макдон*", "kfc", "столов*", "бар", "доставк*", "чаевые", "фастфуд",
                         "десерт*", "мороженое", "плов", "шашлык*", "лагман"],
    "Транспорт": ["такси", "метро", "автобус*", "маршрутк*", "проезд", "билет*", "электричк*", "самокат*",
                  "трамва*", "каршеринг*", "uber", "bolt"],
    "Авто": ["бензин*", "заправк*", "азс", "мойк*", "парковк*", "шиномонтаж*", "запчаст*", "осаго", "штраф*",
             "автосервис*", "сто", "диагностик*", "антифриз", "шин*", "резин*", "аккумулятор*", "авто", "машин*"],
    "Жильё": ["аренд*", "квартир*", "коммунал*", "жкх", "свет", "электричеств*", "газ", "ипотек*", "мебел*",
              "уборк*", "ремонт*"],
    "Связь и интернет": ["телефон*", "связь", "интернет*", "мобильн*", "сим", "тариф*", "мтс", "билайн", "мегафон",
                         "теле2", "wifi", "вайфай", "роутер*"],
    "Здоровье": ["аптек*", "лекарств*", "врач*", "стоматолог*", "зуб*", "анализ*", "больниц*", "клиник*",
                 "таблетк*", "витамин*", "массаж*", "поликлиник*", "узи", "мрт"],
    "Одежда": ["одежд*", "куртк*", "кроссовк*", "обув*", "джинс*", "футболк*", "рубашк*", "плать*", "шапк*",
               "ботинк*", "пальто", "костюм*", "носки", "бельё", "белье", "сумк*"],
    "Красота": ["парикмахер*", "стрижк*", "барбер*", "маникюр*", "косметик*", "салон*", "духи", "педикюр*",
                "брови", "ресниц*"],
    "Семья и дети": ["детск*", "ребенк*", "ребёнк*", "ребенок", "ребёнок", "игрушк*", "памперс*", "подгузник*",
                     "садик", "кружок"],
    "Развлечения": ["кино", "театр*", "концерт*", "игр*", "боулинг", "клуб*", "караоке", "развлечен*", "цирк",
                    "выставк*", "бильярд", "steam", "playstation"],
    "Подписки": ["подписк*", "netflix", "spotify", "youtube", "icloud", "chatgpt", "claude", "премиум", "ютуб",
                 "нетфликс", "спотифай"],
    "Образование": ["курс*", "учеб*", "книг*", "школ*", "универ*", "репетитор*", "обучен*", "семинар*",
                    "тренинг*", "вебинар*"],
    "Подарки": ["подар*", "цветы", "цветов", "букет*"],
    "Путешествия": ["отел*", "гостиниц*", "авиабилет*", "самолет*", "самолёт*", "виз*", "тур", "туры", "хостел*",
                    "путешеств*", "аэропорт*", "багаж"],
    "Бизнес-расходы": ["реклам*", "налог*", "оборудован*", "инструмент*", "сотрудник*", "товар*", "закупк*",
                       "поставщик*", "патент"],
}
KEYWORDS = [(cat, [norm(w) for w in words]) for cat, words in EXPENSE_KEYWORDS.items()]

STOP_WORDS = {norm(w) for w in [
    "покупка", "купил", "купила", "купили", "потратил", "потратила", "оплатил", "оплатила", "заплатил",
    "заплатила", "отдал", "отдала", "за", "на", "и", "в", "руб", "рублей", "рубля", "рубль", "р", "₽", "мне",
    "расход", "трата", "добавь", "запиши", "еще", "ещё", "получил", "получила", "пришло", "пришла", "потрачено",
]}

INCOME_RE = re.compile(
    r"зарплат|аванс|преми|получил|пришл|заработал|доход|выручк|кешбэк|кэшбэк|возврат|подарил|продал|"
    r"дивиденд|подработ|фриланс|перевели|прибыл"
)
AMOUNT_RE = re.compile(
    r"(?<![\w.])(\d{1,3}(?:[ \u00a0]\d{3})+|\d+)(?:[.,](\d{1,2})(?!\d))?(?:\s*(тысяч\w*|тыс\.?|к|k)(?!\w))?",
    re.I,
)


def _tokens(s: str):
    s = re.sub(r"[,;:!?()\"'«»—–\-/]+", " ", s.lower())
    out = []
    for t in s.split():
        t = t.strip(".")
        if t and norm(t) not in STOP_WORDS:
            out.append(t)
    return out


def income_category(seg: str) -> str:
    s = norm(seg)
    if re.search(r"зарплат|аванс|преми", s):
        return "Зарплата"
    if re.search(r"подработ|фриланс|халтур", s):
        return "Подработка"
    if re.search(r"выручк|бизнес|продал|прибыл|клиент", s):
        return "Бизнес"
    if "подарил" in s:
        return "Подарок"
    return "Другое"


def match_category(tokens, user_rules) -> str:
    for t in tokens:
        if t in user_rules:
            return user_rules[t]
    for cat, words in KEYWORDS:
        for w in words:
            if w.endswith("*"):
                if any(t.startswith(w[:-1]) for t in tokens):
                    return cat
            elif w in tokens:
                return cat
    return "Другое"


def rules_parse(text: str, user_rules=None):
    user_rules = user_rules or {}
    matches = list(AMOUNT_RE.finditer(text))
    items, used_end = [], 0
    for i, m in enumerate(matches):
        amount = float(m.group(1).replace(" ", "").replace("\u00a0", "") + ("." + m.group(2) if m.group(2) else ""))
        if m.group(3):
            amount *= 1000
        if amount <= 0:
            continue
        prev_end = matches[i - 1].end() if i else 0
        next_start = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        before = text[max(prev_end, used_end):m.start()]
        if _tokens(before):
            raw = before
        else:
            raw = text[m.end():next_start]
            used_end = next_start
        tokens = _tokens(raw)
        ntok = [norm(t) for t in tokens]
        seg = raw if len(matches) > 1 else text
        nseg = norm(seg)
        if "зарплат" in nseg and re.search(r"сотрудник|работник|мастер", nseg):
            kind, cat = "expense", "Бизнес-расходы"
        elif INCOME_RE.search(nseg):
            kind, cat = "income", income_category(seg)
        else:
            kind, cat = "expense", match_category(ntok, user_rules)
        items.append({"kind": kind, "amount": round(amount, 2), "category": cat, "note": " ".join(tokens)[:80]})
    return items


def load_user_rules(user_id: int) -> dict:
    with db() as c:
        rows = c.execute("SELECT word, category FROM rules WHERE user_id=?", (user_id,)).fetchall()
    return {r["word"]: r["category"] for r in rows}


async def parse_text(text: str, user_id: int):
    rules = load_user_rules(user_id)
    if claude is None:
        return rules_parse(text, rules)
    try:
        resp = await claude.messages.create(
            model=MODEL,
            max_tokens=600,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": text}],
        )
        raw = "".join(b.text for b in resp.content if b.type == "text").strip()
        raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.M).strip()
        data = json.loads(raw)
        items = []
        for it in data.get("items", []):
            amount = float(it["amount"])
            if amount <= 0:
                continue
            kind = "income" if it.get("kind") == "income" else "expense"
            cats = INCOME_CATS if kind == "income" else EXPENSE_CATS
            cat = it.get("category") if it.get("category") in cats else "Другое"
            note = str(it.get("note", ""))[:80]
            if kind == "expense":  # выученные слова важнее выбора ИИ
                for t in _tokens(note):
                    if norm(t) in rules:
                        cat = rules[norm(t)]
            items.append({"kind": kind, "amount": round(amount, 2), "category": cat, "note": note})
        return items
    except Exception:
        log.exception("Claude parse failed, using rules")
        return rules_parse(text, rules)


# ---------- Основная логика ----------
def month_spent(c, user_id: int, category: str) -> float:
    return c.execute(
        "SELECT COALESCE(SUM(amount),0) AS total FROM transactions "
        "WHERE user_id=? AND kind='expense' AND category=? AND created_at>=?",
        (user_id, category, period_start("month", user_timezone(user_id))),
    ).fetchone()["total"]


def budget_warnings(user_id: int, items):
    if not user_settings(user_id)["budget_notifications"]:
        return []
    msgs, seen = [], set()
    month_key = period_start("month", user_timezone(user_id))
    with db() as c:
        for it in items:
            cat = it["category"]
            if it["kind"] != "expense" or cat in seen:
                continue
            seen.add(cat)
            row = c.execute(
                "SELECT limit_amount FROM budgets WHERE user_id=? AND category=?",
                (user_id, cat),
            ).fetchone()
            if not row:
                continue
            spent, lim = month_spent(c, user_id, cat), row["limit_amount"]
            pct = spent / lim * 100
            if pct > 100:
                level, message, passed = "over", f"🔴 Лимит «{cat}» превышен: {money(spent)} из {money(lim)}", ("80", "100", "over")
            elif pct >= 100:
                level, message, passed = "100", f"⚠️ Лимит «{cat}» достигнут: {money(spent)} из {money(lim)}", ("80", "100")
            elif pct >= 80:
                level, message, passed = "80", f"⚠️ Использовано 80% бюджета «{cat}»: {money(spent)} из {money(lim)}", ("80",)
            else:
                continue
            previous = c.execute(
                "SELECT 1 FROM budget_alerts WHERE user_id=? AND category=? AND month_key=? AND level=?",
                (user_id, cat, month_key, level),
            ).fetchone()
            if previous:
                continue
            now = datetime.now(timezone.utc).isoformat()
            c.executemany(
                "INSERT INTO budget_alerts(user_id,category,month_key,level,sent_at) VALUES (?,?,?,?,?) "
                "ON CONFLICT(user_id,category,month_key,level) DO NOTHING",
                [(user_id, cat, month_key, item, now) for item in passed],
            )
            msgs.append(message)
    return msgs


def save_parsed_items(user_id: int, items) -> str:
    if not items:
        return "Не нашёл сумму. Напишите, например: «вода 50» или «зарплата 80000»."
    now = datetime.now(timezone.utc).isoformat()
    lines = []
    with db() as c:
        for it in items:
            cur = c.execute(
                "INSERT INTO transactions(user_id,kind,amount,category,note,created_at) VALUES (?,?,?,?,?,?) RETURNING id",
                (user_id, it["kind"], it["amount"], it["category"], it["note"], now),
            )
            tx_id = cur.fetchone()["id"]
            label = "Расход" if it["kind"] == "expense" else "Доход"
            sign = "−" if it["kind"] == "expense" else "+"
            note = f" · {it['note']}" if it["note"] else ""
            lines.append(f"✅ {label}: {sign}{money(it['amount'])} · {it['category']}{note}  (отмена: /del {tx_id})")
            if it["kind"] == "expense" and it["category"] == "Другое":
                lines.append(f"❓ Категория не определена. Выберите: /cat {tx_id} Продукты (любая из /categories), и я запомню слово.")
    lines += budget_warnings(user_id, items)
    return "\n".join(lines)


async def process_text(user_id: int, text: str) -> str:
    return save_parsed_items(user_id, await parse_text(text, user_id))


def stats_data(user_id: int, period: str) -> dict:
    since = period_start(period, user_timezone(user_id))
    with db() as c:
        def total(kind):
            return c.execute(
                "SELECT COALESCE(SUM(amount),0) AS total FROM transactions WHERE user_id=? AND kind=? AND created_at>=?",
                (user_id, kind, since),
            ).fetchone()["total"]
        inc, exp = total("income"), total("expense")
        cats = c.execute(
            "SELECT category, SUM(amount) s FROM transactions "
            "WHERE user_id=? AND kind='expense' AND created_at>=? GROUP BY category ORDER BY s DESC",
            (user_id, since),
        ).fetchall()
    categories = [
        {"category": r["category"], "amount": r["s"], "share": (r["s"] / exp * 100 if exp else 0)}
        for r in cats
    ]
    return {"period": period, "income": inc, "expense": exp, "balance": inc - exp, "categories": categories}


def overall_balance(user_id: int) -> float:
    with db() as c:
        income = c.execute(
            "SELECT COALESCE(SUM(amount),0) AS total FROM transactions WHERE user_id=? AND kind='income'",
            (user_id,),
        ).fetchone()["total"]
        expense = c.execute(
            "SELECT COALESCE(SUM(amount),0) AS total FROM transactions WHERE user_id=? AND kind='expense'",
            (user_id,),
        ).fetchone()["total"]
    return income - expense


def analytics_series(user_id: int, period: str) -> list[dict]:
    tz = user_timezone(user_id)
    now = datetime.now(tz)
    if period == "today":
        buckets = [(now.replace(hour=hour, minute=0, second=0, microsecond=0), f"{hour:02d}:00") for hour in range(24)]
        since = period_start("today", tz)
    elif period == "week":
        monday = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=now.weekday())
        weekday_names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
        buckets = [(monday + timedelta(days=day), weekday_names[day]) for day in range(7)]
        since = monday.astimezone(timezone.utc).isoformat()
    elif period == "year":
        year_start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        buckets = [(year_start.replace(month=month), f"{month:02d}") for month in range(1, 13)]
        since = year_start.astimezone(timezone.utc).isoformat()
    else:
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        days = (month_start.replace(month=12, day=31) if month_start.month == 12 else month_start.replace(month=month_start.month + 1, day=1) - timedelta(days=1)).day
        buckets = [(month_start + timedelta(days=day), str(day + 1)) for day in range(days)]
        since = month_start.astimezone(timezone.utc).isoformat()
    totals = {label: 0.0 for _, label in buckets}
    with db() as c:
        rows = c.execute(
            "SELECT created_at, amount FROM transactions WHERE user_id=? AND kind='expense' AND created_at>=?",
            (user_id, since),
        ).fetchall()
    for row in rows:
        created = local_dt(row["created_at"], tz)
        if period == "today":
            label = f"{created.hour:02d}:00"
        elif period == "year":
            label = f"{created.month:02d}"
        else:
            label = str(created.day) if period == "month" else created.strftime("%a")
        if label in totals:
            totals[label] += row["amount"]
    return [{"label": label, "amount": round(totals[label], 2)} for _, label in buckets]


def financial_insights(user_id: int, period: str, stats: dict) -> list[str]:
    insights = []
    if stats["categories"]:
        top = stats["categories"][0]
        if top["share"] >= 1:
            insights.append(f"Категория «{top['category']}» составляет {top['share']:.0f}% расходов за период.")
    if stats["income"] or stats["expense"]:
        if stats["balance"] > 0:
            insights.append("За выбранный период доходы превышают расходы.")
        elif stats["balance"] < 0:
            insights.append("За выбранный период расходы превышают доходы.")
        else:
            insights.append("За выбранный период доходы равны расходам.")
    if period == "week":
        tz = user_timezone(user_id)
        current_start = datetime.fromisoformat(period_start("week", tz))
        previous_start = (current_start - timedelta(days=7)).isoformat()
        with db() as c:
            previous_expense = c.execute(
                "SELECT COALESCE(SUM(amount),0) AS total FROM transactions "
                "WHERE user_id=? AND kind='expense' AND created_at>=? AND created_at<?",
                (user_id, previous_start, current_start.isoformat()),
            ).fetchone()["total"]
        if previous_expense > 0:
            change = (stats["expense"] - previous_expense) / previous_expense * 100
            if abs(change) >= 1:
                direction = "больше" if change > 0 else "меньше"
                insights.append(f"Расходы {direction} прошлой недели на {abs(change):.0f}%.")
    return insights


def stats_text(user_id: int, period: str) -> str:
    titles = {"today": "Сегодня", "week": "Эта неделя", "month": "Этот месяц", "year": "Этот год"}
    d = stats_data(user_id, period)
    out = [
        f"📊 {titles[period]}",
        f"Доходы: +{money(d['income'])}",
        f"Расходы: −{money(d['expense'])}",
        f"Баланс: {money(d['balance'])}",
    ]
    if d["categories"]:
        out.append("\nРасходы по категориям:")
        for r in d["categories"]:
            out.append(f"• {r['category']}: {money(r['amount'])} ({r['share']:.0f}%)")
    else:
        out.append("\nЗаписей пока нет.")
    return "\n".join(out)


def tx_payload(r, user_id: int) -> dict:
    return {
        "id": r["id"],
        "kind": r["kind"],
        "amount": r["amount"],
        "amount_text": money(r["amount"]),
        "category": r["category"],
        "note": r["note"] or "",
        "created_at": r["created_at"],
        "when": local_dt(r["created_at"], user_timezone(user_id)).strftime("%d.%m %H:%M"),
        "datetime": local_dt(r["created_at"], user_timezone(user_id)).isoformat(timespec="minutes"),
    }


def app_url() -> str:
    return f"{PUBLIC_URL}/app" if PUBLIC_URL else ""


def nav_keyboard() -> ReplyKeyboardMarkup:
    rows = []
    url = app_url()
    if url:
        rows.append([KeyboardButton(text="📊 Мои финансы", web_app=WebAppInfo(url=url)), KeyboardButton(text="➕ Добавить")])
    else:
        rows.append([KeyboardButton(text="📊 Мои финансы"), KeyboardButton(text="➕ Добавить")])
    rows.append([KeyboardButton(text="📜 История"), KeyboardButton(text="📈 Статистика")])
    rows.append([KeyboardButton(text="🎯 Цели"), KeyboardButton(text="💰 Бюджеты")])
    rows.append([KeyboardButton(text="⚙️ Настройки")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def app_inline() -> InlineKeyboardMarkup | None:
    url = app_url()
    if not url:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Открыть приложение", web_app=WebAppInfo(url=url))],
        [InlineKeyboardButton(text="Открыть чат бота", url=f"https://t.me/{BOT_USERNAME}")],
    ])


def validate_init_data(init_data: str):
    parsed = dict(parse_qsl(init_data, keep_blank_values=True))
    received = parsed.pop("hash", "")
    if not received:
        return None
    check = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    calc = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc, received):
        return None
    try:
        if time.time() - int(parsed.get("auth_date", "0")) > 86400 * 2:
            return None
    except ValueError:
        return None
    try:
        return json.loads(parsed.get("user") or "{}")
    except json.JSONDecodeError:
        return None


def resolve_app_user(request: web.Request):
    init_data = request.headers.get("X-Telegram-Init-Data") or request.query.get("initData", "")
    if init_data:
        user = validate_init_data(init_data)
        if user and user.get("id") and allowed(int(user["id"])):
            uid = int(user["id"])
            request["telegram_user"] = user
            ensure_user(uid)
            return uid
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        uid = user_by_token(auth[7:].strip())
        if uid and allowed(uid):
            return uid
    peer = request.remote
    if APP_DEV and peer in ("127.0.0.1", "::1"):
        with db() as c:
            row = c.execute("SELECT user_id FROM users LIMIT 1").fetchone()
        if row:
            return row["user_id"]
        return ensure_user(1)
    return None


async def require_app_user(request: web.Request) -> int:
    uid = resolve_app_user(request)
    if not uid:
        raise web.HTTPUnauthorized(text='{"ok":false,"error":"unauthorized"}', content_type="application/json")
    return uid


def build_xlsx(user_id: int) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Операции"
    ws.append(["ID", "Дата", "Тип", "Категория", "Сумма, ₽", "Комментарий"])
    with db() as c:
        rows = c.execute(
            "SELECT id, kind, amount, category, note, created_at FROM transactions "
            "WHERE user_id=? ORDER BY created_at",
            (user_id,),
        ).fetchall()
    totals = {}
    for r in rows:
        kind = "Расход" if r["kind"] == "expense" else "Доход"
        ws.append([r["id"], local_dt(r["created_at"], user_timezone(user_id)).strftime("%Y-%m-%d %H:%M"), kind,
                   r["category"], r["amount"], r["note"] or ""])
        totals[(kind, r["category"])] = totals.get((kind, r["category"]), 0) + r["amount"]
    for col, width in zip("ABCDEF", (8, 18, 10, 22, 14, 30)):
        ws.column_dimensions[col].width = width
    ws2 = wb.create_sheet("По категориям")
    ws2.append(["Тип", "Категория", "Сумма, ₽"])
    for (kind, cat), s in sorted(totals.items()):
        ws2.append([kind, cat, s])
    ws2.column_dimensions["A"].width = 10
    ws2.column_dimensions["B"].width = 24
    ws2.column_dimensions["C"].width = 14
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def find_category(name: str, cats=None):
    cats = cats or EXPENSE_CATS
    name = name.strip().lower()
    for cat in cats:
        if cat.lower() == name:
            return cat
    for cat in cats:
        if name and cat.lower().startswith(name):
            return cat
    return None


# ---------- Команды Telegram ----------
HELP = """Я веду ваши доходы и расходы.

Кнопки внизу — быстрая навигация. «Приложение» открывает Mini App.

Пишите как удобно:
• вода 50
• такси 350 и кофе 200
• зарплата 80000

Команды:
/app — открыть приложение
/today /week /month /year — статистика
/last — последние записи, /del ID — удалить запись, /undo — удалить последнюю
/budget Продукты 20000 — месячный лимит на категорию (0 — убрать лимит)
/budgets — состояние бюджетов
/categories — список категорий
/cat ID Категория — исправить категорию записи (бот запомнит слово на будущее)
/rules — чему вы научили бота, /unrule слово — забыть слово
/export — выгрузка в Excel
/token — ссылка и ключ для команды на iPhone"""


@dp.message(Command("start", "help"))
async def cmd_start(m: Message):
    with db() as c:
        is_new = c.execute("SELECT 1 FROM users WHERE user_id=?", (m.from_user.id,)).fetchone() is None
    ensure_user(m.from_user.id)
    pending_add.discard(m.from_user.id)
    if is_new:
        greeting = (
            f"Привет, {m.from_user.first_name}! 👋\n\n"
            "Добро пожаловать в Tracker Finance. Я помогу учитывать доходы и расходы, следить за бюджетом и целями.\n\n"
            "Попробуйте написать: «кофе 250»."
        )
    else:
        greeting = "С возвращением! Напишите операцию или выберите раздел в меню."
    if not app_url():
        greeting += "\n\nФинансовая панель появится в Telegram после настройки публичного HTTPS-адреса."
    await m.answer(greeting, reply_markup=nav_keyboard())
    kb = app_inline()
    if kb:
        await m.answer("Откройте финансовую панель:", reply_markup=kb)


@dp.message(Command("app"))
async def cmd_app(m: Message):
    kb = app_inline()
    if not kb:
        return await m.answer(
            "Mini App ещё без публичного адреса. Задайте PUBLIC_URL (HTTPS) и перезапустите бота.",
            reply_markup=nav_keyboard(),
        )
    await m.answer("Нажмите кнопку, чтобы открыть приложение.", reply_markup=kb)


@dp.message(Command("today"))
async def cmd_today(m: Message):
    await m.answer(stats_text(m.from_user.id, "today"))


@dp.message(Command("week"))
async def cmd_week(m: Message):
    await m.answer(stats_text(m.from_user.id, "week"))


@dp.message(Command("month"))
async def cmd_month(m: Message):
    await m.answer(stats_text(m.from_user.id, "month"))


@dp.message(Command("year"))
async def cmd_year(m: Message):
    await m.answer(stats_text(m.from_user.id, "year"))


@dp.message(Command("admin"))
async def cmd_admin(m: Message):
    if not is_admin(m.from_user.id):
        return await m.answer("Эта команда доступна только администратору.")
    with db() as c:
        users = c.execute("SELECT COUNT(*) AS total FROM users").fetchone()["total"]
        operations = c.execute("SELECT COUNT(*) AS total FROM transactions").fetchone()["total"]
        budgets = c.execute("SELECT COUNT(*) AS total FROM budgets").fetchone()["total"]
        goals = c.execute("SELECT COUNT(*) AS total FROM goals").fetchone()["total"]
    await m.answer(
        "🛡 Панель администратора\n"
        f"Пользователей: {users}\n"
        f"Операций: {operations}\n"
        f"Бюджетов: {budgets}\n"
        f"Целей: {goals}"
    )


@dp.message(Command("categories"))
async def cmd_categories(m: Message):
    await m.answer("Расходы: " + ", ".join(EXPENSE_CATS) + "\n\nДоходы: " + ", ".join(INCOME_CATS))


@dp.message(Command("last"))
async def cmd_last(m: Message):
    with db() as c:
        rows = c.execute(
            "SELECT id, kind, amount, category, note, created_at FROM transactions "
            "WHERE user_id=? ORDER BY id DESC LIMIT 10",
            (m.from_user.id,),
        ).fetchall()
    if not rows:
        return await m.answer("Записей пока нет.")
    lines = []
    for r in rows:
        sign = "−" if r["kind"] == "expense" else "+"
        lines.append(f"#{r['id']} {local_dt(r['created_at'], user_timezone(m.from_user.id)).strftime('%d.%m %H:%M')} "
                     f"{sign}{money(r['amount'])} · {r['category']} · {r['note'] or ''}")
    await m.answer("\n".join(lines) + "\n\nУдалить: /del ID")


@dp.message(Command("del"))
async def cmd_del(m: Message, command: CommandObject):
    arg = (command.args or "").strip().lstrip("#")
    if not arg.isdigit():
        return await m.answer("Укажите номер записи: /del 12 (номера видно в /last)")
    with db() as c:
        cur = c.execute("DELETE FROM transactions WHERE id=? AND user_id=?", (int(arg), m.from_user.id))
    await m.answer("🗑 Удалено." if cur.rowcount else "Запись с таким номером не найдена.")


@dp.message(Command("undo"))
async def cmd_undo(m: Message):
    with db() as c:
        row = c.execute("SELECT id FROM transactions WHERE user_id=? ORDER BY id DESC LIMIT 1",
                        (m.from_user.id,)).fetchone()
        if not row:
            return await m.answer("Нечего удалять.")
        c.execute("DELETE FROM transactions WHERE id=?", (row["id"],))
    await m.answer("🗑 Последняя запись удалена.")


@dp.message(Command("budget"))
async def cmd_budget(m: Message, command: CommandObject):
    args = (command.args or "").strip()
    match = re.match(r"^(.+?)\s+(\d[\d\s]*(?:[.,]\d+)?)\s*$", args)
    if not match:
        return await m.answer("Формат: /budget Продукты 20000\nКатегории: /categories")
    cat = find_category(match.group(1))
    if not cat:
        return await m.answer("Не нашёл такую категорию. Список: /categories")
    limit = float(match.group(2).replace(" ", "").replace(",", "."))
    with db() as c:
        if limit == 0:
            c.execute("DELETE FROM budgets WHERE user_id=? AND category=?", (m.from_user.id, cat))
            return await m.answer(f"Лимит на «{cat}» убран.")
        c.execute(
            "INSERT INTO budgets(user_id, category, limit_amount) VALUES (?,?,?) "
            "ON CONFLICT(user_id, category) DO UPDATE SET limit_amount=excluded.limit_amount",
            (m.from_user.id, cat, limit),
        )
    await m.answer(f"✅ Лимит на «{cat}»: {money(limit)} в месяц.")


@dp.message(Command("budgets"))
async def cmd_budgets(m: Message):
    with db() as c:
        rows = c.execute("SELECT category, limit_amount FROM budgets WHERE user_id=? ORDER BY category",
                         (m.from_user.id,)).fetchall()
        if not rows:
            return await m.answer("Лимитов пока нет. Пример: /budget Продукты 20000")
        lines = ["💰 Бюджеты на этот месяц:"]
        for r in rows:
            spent = month_spent(c, m.from_user.id, r["category"])
            pct = spent / r["limit_amount"] * 100
            filled = min(10, int(pct // 10))
            bar = "█" * filled + "░" * (10 - filled)
            lines.append(f"{r['category']}: {bar} {pct:.0f}%\n   {money(spent)} из {money(r['limit_amount'])}")
    await m.answer("\n".join(lines))


@dp.message(Command("export"))
async def cmd_export(m: Message):
    data = build_xlsx(m.from_user.id)
    name = f"finance_{datetime.now(TZ).strftime('%Y-%m-%d')}.xlsx"
    await m.answer_document(BufferedInputFile(data, filename=name), caption="Ваши операции в Excel")


@dp.message(Command("cat"))
async def cmd_cat(m: Message, command: CommandObject):
    mt = re.match(r"^#?(\d+)\s+(.+)$", (command.args or "").strip())
    if not mt:
        return await m.answer("Формат: /cat 12 Продукты\nНомер записи виден в /last, категории в /categories")
    tx_id, name = int(mt.group(1)), mt.group(2)
    with db() as c:
        row = c.execute("SELECT kind, note FROM transactions WHERE id=? AND user_id=?",
                        (tx_id, m.from_user.id)).fetchone()
        if not row:
            return await m.answer("Запись с таким номером не найдена.")
        cats = INCOME_CATS if row["kind"] == "income" else EXPENSE_CATS
        cat = find_category(name, cats)
        if not cat:
            return await m.answer("Не нашёл такую категорию. Список: /categories")
        c.execute("UPDATE transactions SET category=? WHERE id=?", (cat, tx_id))
        words = [norm(t) for t in _tokens(row["note"] or "") if len(t) >= 3]
        if row["kind"] == "expense":
            for w in words:
                c.execute(
                    "INSERT INTO rules(user_id, word, category) VALUES (?,?,?) "
                    "ON CONFLICT(user_id, word) DO UPDATE SET category=excluded.category",
                    (m.from_user.id, w, cat),
                )
    learned = f" Запомнил: {', '.join(words)} → {cat}." if words and row["kind"] == "expense" else ""
    await m.answer(f"✅ Категория записи #{tx_id}: {cat}.{learned}")


@dp.message(Command("rules"))
async def cmd_rules(m: Message):
    rules = load_user_rules(m.from_user.id)
    if not rules:
        return await m.answer("Пока ничему не учили. Если категория выбрана неверно: /cat ID Категория")
    await m.answer("🧠 Мои знания о ваших словах:\n" + "\n".join(f"• {w} → {c}" for w, c in sorted(rules.items())))


@dp.message(Command("unrule"))
async def cmd_unrule(m: Message, command: CommandObject):
    word = norm((command.args or "").strip())
    if not word:
        return await m.answer("Формат: /unrule слово")
    with db() as c:
        cur = c.execute("DELETE FROM rules WHERE user_id=? AND word=?", (m.from_user.id, word))
    await m.answer("Забыл." if cur.rowcount else "Такого слова нет в /rules.")


@dp.message(F.text.in_({"📊 Мои финансы", "➕ Добавить", "📜 История", "📈 Статистика", "🎯 Цели", "💰 Бюджеты", "⚙️ Настройки"}))
async def on_nav(m: Message):
    ensure_user(m.from_user.id)
    t = m.text
    if t == "📊 Мои финансы":
        return await cmd_app(m)
    if t == "➕ Добавить":
        pending_add.add(m.from_user.id)
        return await m.answer("Напишите операцию одним сообщением, например: «такси 350 и кофе 200».", reply_markup=nav_keyboard())
    pending_add.discard(m.from_user.id)
    if t == "💰 Бюджеты":
        return await cmd_budgets(m)
    if t == "🎯 Цели":
        with db() as c:
            goals = c.execute(
                "SELECT title, target_amount, saved_amount FROM goals "
                "WHERE user_id=? ORDER BY id DESC",
                (m.from_user.id,),
            ).fetchall()
        if not goals:
            text = "🎯 Целей пока нет. Создайте первую во вкладке «Цели» в приложении."
        else:
            lines = ["🎯 Ваши цели:"]
            for goal in goals:
                pct = min(100, round(goal["saved_amount"] / goal["target_amount"] * 100))
                lines.append(
                    f"• {goal['title']}: {money(goal['saved_amount'])} из "
                    f"{money(goal['target_amount'])} ({pct}%)"
                )
            text = "\n".join(lines) + "\n\nПополнять цели можно в мини-приложении."
        return await m.answer(text, reply_markup=nav_keyboard())
    if t == "⚙️ Настройки":
        text = "Тема, часовой пояс и уведомления настраиваются в профиле Mini App. Валюта этой версии — рубли."
        if not app_url():
            text += "\nДля Mini App нужен публичный HTTPS-адрес (PUBLIC_URL)."
        return await m.answer(text + "\nДля интеграции с iPhone: /token", reply_markup=nav_keyboard())
    if t == "📈 Статистика":
        return await m.answer(stats_text(m.from_user.id, "month"), reply_markup=nav_keyboard())
    if t == "📜 История":
        return await cmd_last(m)
    if t == "Помощь":
        return await m.answer(HELP, reply_markup=nav_keyboard())
    await m.answer(HELP, reply_markup=nav_keyboard())


@dp.message(Command("token"))
async def cmd_token(m: Message):
    token = ensure_user(m.from_user.id)
    url = f"{PUBLIC_URL}/api/add" if PUBLIC_URL else "(адрес сервера, см. инструкцию)"
    await m.answer(
        "🔑 Данные для команды на iPhone.\n"
        f"Адрес: {url}\nКлюч (token): {token}\n\n"
        "Никому не показывайте ключ — с ним можно добавлять записи от вашего имени."
    )


@dp.message(F.text & ~F.text.startswith("/"))
async def on_text(m: Message):
    ensure_user(m.from_user.id)
    pending_add.discard(m.from_user.id)
    await m.answer(await process_text(m.from_user.id, m.text), reply_markup=nav_keyboard())


# ---------- Веб-адрес для iPhone-команды ----------
async def api_add(request: web.Request):
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "bad json"}, status=400)
    user_id = user_by_token(str(data.get("token", "")))
    if not user_id or not allowed(user_id):
        return web.json_response({"ok": False, "error": "unauthorized"}, status=401)
    text = str(data.get("text", "")).strip()
    if not text:
        return web.json_response({"ok": False, "error": "empty text"}, status=400)
    reply = await process_text(user_id, text)
    try:
        await bot.send_message(user_id, reply)
    except Exception:
        log.exception("Cannot notify user")
    return web.json_response({"ok": True, "reply": reply})


async def app_index(_request: web.Request):
    return web.FileResponse(os.path.join(WEBAPP_DIR, "index.html"))


async def app_script(_request: web.Request):
    return web.FileResponse(os.path.join(WEBAPP_DIR, "app.js"))


async def api_app_me(request: web.Request):
    user_id = await require_app_user(request)
    ensure_user(user_id)
    settings = user_settings(user_id)
    telegram_user = request.get("telegram_user", {})
    return web.json_response({
        "ok": True,
        "categories": {"expense": EXPENSE_CATS, "income": INCOME_CATS},
        "display_name": telegram_user.get("first_name", "Друг"),
        "user_id": user_id,
        "overall_balance": overall_balance(user_id),
        "settings": settings,
    })


async def api_app_settings(request: web.Request):
    user_id = await require_app_user(request)
    if request.method == "GET":
        current = user_settings(user_id)
        return web.json_response({
            "ok": True,
            "settings": {key: current[key] for key in ("theme", "timezone", "budget_notifications", "weekly_summary")},
            "timezones": ["Europe/Moscow", "Europe/Kaliningrad", "Europe/Minsk", "Asia/Dushanbe", "Asia/Almaty", "Asia/Tashkent"],
        })
    try:
        data = await request.json()
    except (json.JSONDecodeError, web.HTTPBadRequest):
        return web.json_response({"ok": False, "error": "Некорректный JSON"}, status=400)
    current = user_settings(user_id)
    theme = data.get("theme", current["theme"])
    tz_name = data.get("timezone", current["timezone"])
    budget_notifications = int(bool(data.get("budget_notifications", current["budget_notifications"])))
    weekly_summary = int(bool(data.get("weekly_summary", current["weekly_summary"])))
    if theme not in {"system", "light", "dark"}:
        return web.json_response({"ok": False, "error": "Некорректная тема"}, status=400)
    try:
        ZoneInfo(tz_name)
    except (TypeError, ValueError, KeyError):
        return web.json_response({"ok": False, "error": "Некорректный часовой пояс"}, status=400)
    with db() as c:
        c.execute(
            "UPDATE user_settings SET theme=?,timezone=?,budget_notifications=?,weekly_summary=? WHERE user_id=?",
            (theme, tz_name, budget_notifications, weekly_summary, user_id),
        )
    return web.json_response({"ok": True})


async def api_app_export(request: web.Request):
    user_id = await require_app_user(request)
    data = build_xlsx(user_id)
    filename = f"finance_{datetime.now(user_timezone(user_id)).strftime('%Y-%m-%d')}.xlsx"
    return web.Response(
        body=data,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


async def api_app_delete_data(request: web.Request):
    user_id = await require_app_user(request)
    with db() as c:
        for table in ("transactions", "budgets", "goals", "rules", "budget_alerts", "weekly_reports", "deleted_transactions"):
            c.execute(f"DELETE FROM {table} WHERE user_id=?", (user_id,))
    return web.json_response({"ok": True})


async def weekly_summary_loop():
    while True:
        with db() as c:
            user_ids = [row["user_id"] for row in c.execute(
                "SELECT user_id FROM user_settings WHERE weekly_summary=1"
            ).fetchall()]
        for user_id in user_ids:
            tz = user_timezone(user_id)
            now = datetime.now(tz)
            if now.weekday() != 0 or now.hour < 9:
                continue
            week_key = period_start("week", tz)
            with db() as c:
                sent = c.execute(
                    "SELECT 1 FROM weekly_reports WHERE user_id=? AND week_key=?",
                    (user_id, week_key),
                ).fetchone()
            if sent:
                continue
            stats = stats_data(user_id, "week")
            if not stats["income"] and not stats["expense"]:
                continue
            top = stats["categories"][0]["category"] if stats["categories"] else "нет расходов"
            text = (
                "📊 Сводка за неделю\n"
                f"Доходы: +{money(stats['income'])}\n"
                f"Расходы: −{money(stats['expense'])}\n"
                f"Разница: {money(stats['balance'])}\n"
                f"Самая крупная категория: {top}"
            )
            try:
                await bot.send_message(user_id, text)
            except Exception:
                log.exception("Cannot send weekly summary to user %s", user_id)
                continue
            with db() as c:
                c.execute(
                    "INSERT INTO weekly_reports(user_id,week_key,sent_at) VALUES (?,?,?) "
                    "ON CONFLICT(user_id,week_key) DO NOTHING",
                    (user_id, week_key, datetime.now(timezone.utc).isoformat()),
                )
        await asyncio.sleep(300)


async def api_app_stats(request: web.Request):
    user_id = await require_app_user(request)
    period = request.query.get("period", "today")
    if period not in {"today", "week", "month", "year"}:
        return web.json_response({"ok": False, "error": "invalid period"}, status=400)
    stats = stats_data(user_id, period)
    return web.json_response({
        "ok": True,
        **stats,
        "overall_balance": overall_balance(user_id),
        "series": analytics_series(user_id, period),
        "insights": financial_insights(user_id, period, stats),
    })


async def api_app_transactions(request: web.Request):
    user_id = await require_app_user(request)
    kind = request.query.get("kind", "all")
    category = request.query.get("category", "").strip()
    search = request.query.get("q", "").strip()
    try:
        offset = max(0, int(request.query.get("offset", "0")))
    except ValueError:
        offset = 0
    if kind not in {"all", "income", "expense"}:
        return web.json_response({"ok": False, "error": "invalid kind"}, status=400)
    clauses = ["user_id=?"]
    params = [user_id]
    if kind != "all":
        clauses.append("kind=?")
        params.append(kind)
    if category:
        clauses.append("category=?")
        params.append(category)
    if search:
        clauses.append("(category LIKE ? OR COALESCE(note,'') LIKE ? OR CAST(amount AS TEXT) LIKE ?)")
        params.extend([f"%{search}%"] * 3)
    with db() as c:
        rows = c.execute(
            "SELECT id, kind, amount, category, note, created_at FROM transactions "
            f"WHERE {' AND '.join(clauses)} ORDER BY created_at DESC LIMIT 100 OFFSET ?",
            [*params, offset],
        ).fetchall()
    return web.json_response({
        "ok": True,
        "items": [tx_payload(row, user_id) for row in rows],
        "has_more": len(rows) == 100,
        "next_offset": offset + len(rows),
    })


async def api_app_delete_transaction(request: web.Request):
    user_id = await require_app_user(request)
    tx_id = int(request.match_info["tx_id"])
    with db() as c:
        row = c.execute(
            "SELECT id, kind, amount, category, note, created_at FROM transactions WHERE id=? AND user_id=?",
            (tx_id, user_id),
        ).fetchone()
        if not row:
            return web.json_response({"ok": False, "error": "Запись не найдена"}, status=404)
        c.execute(
            "INSERT INTO deleted_transactions(tx_id,user_id,kind,amount,category,note,created_at,deleted_at) "
            "VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(tx_id) DO UPDATE SET "
            "user_id=excluded.user_id,kind=excluded.kind,amount=excluded.amount,category=excluded.category,"
            "note=excluded.note,created_at=excluded.created_at,deleted_at=excluded.deleted_at",
            (row["id"], user_id, row["kind"], row["amount"], row["category"], row["note"],
             row["created_at"], datetime.now(timezone.utc).isoformat()),
        )
        cur = c.execute(
            "DELETE FROM transactions WHERE id=? AND user_id=?",
            (tx_id, user_id),
        )
    if not cur.rowcount:
        return web.json_response({"ok": False, "error": "Запись не найдена"}, status=404)
    return web.json_response({"ok": True, "undo_id": tx_id})


async def api_app_restore_transaction(request: web.Request):
    user_id = await require_app_user(request)
    tx_id = int(request.match_info["tx_id"])
    with db() as c:
        row = c.execute(
            "SELECT * FROM deleted_transactions WHERE tx_id=? AND user_id=?",
            (tx_id, user_id),
        ).fetchone()
        if not row:
            return web.json_response({"ok": False, "error": "Операцию уже нельзя восстановить"}, status=404)
        c.execute(
            "INSERT INTO transactions(id,user_id,kind,amount,category,note,created_at) VALUES (?,?,?,?,?,?,?)",
            (row["tx_id"], user_id, row["kind"], row["amount"], row["category"], row["note"], row["created_at"]),
        )
        c.execute("DELETE FROM deleted_transactions WHERE tx_id=? AND user_id=?", (tx_id, user_id))
    return web.json_response({"ok": True})


async def api_app_update_transaction(request: web.Request):
    user_id = await require_app_user(request)
    tx_id = int(request.match_info["tx_id"])
    try:
        data = await request.json()
    except (json.JSONDecodeError, web.HTTPBadRequest):
        return web.json_response({"ok": False, "error": "Некорректный JSON"}, status=400)
    with db() as c:
        row = c.execute(
            "SELECT kind, amount, category, note, created_at FROM transactions WHERE id=? AND user_id=?",
            (tx_id, user_id),
        ).fetchone()
        if not row:
            return web.json_response({"ok": False, "error": "Запись не найдена"}, status=404)
        values = dict(row)
        values.update({key: data[key] for key in ("kind", "amount", "category", "note") if key in data})
        if values["kind"] not in {"income", "expense"}:
            return web.json_response({"ok": False, "error": "Некорректный тип операции"}, status=400)
        categories = INCOME_CATS if values["kind"] == "income" else EXPENSE_CATS
        if values["category"] not in categories:
            return web.json_response({"ok": False, "error": "Некорректная категория"}, status=400)
        try:
            values["amount"] = float(str(values["amount"]).replace(" ", "").replace(",", "."))
        except (TypeError, ValueError):
            values["amount"] = 0
        if not math.isfinite(values["amount"]) or values["amount"] <= 0:
            return web.json_response({"ok": False, "error": "Сумма должна быть больше нуля"}, status=400)
        values["note"] = str(values["note"] or "").strip()[:100]
        if "datetime" in data:
            try:
                created = datetime.fromisoformat(str(data["datetime"]))
                if created.tzinfo is None:
                    created = created.replace(tzinfo=user_timezone(user_id))
                values["created_at"] = created.astimezone(timezone.utc).isoformat()
            except ValueError:
                return web.json_response({"ok": False, "error": "Некорректная дата"}, status=400)
        c.execute(
            "UPDATE transactions SET kind=?,amount=?,category=?,note=?,created_at=? WHERE id=? AND user_id=?",
            (values["kind"], values["amount"], values["category"], values["note"], values["created_at"], tx_id, user_id),
        )
        if values["kind"] == "expense" and values["category"] != row["category"]:
            for word in {norm(token) for token in _tokens(values["note"]) if len(token) >= 3}:
                c.execute(
                    "INSERT INTO rules(user_id,word,category) VALUES (?,?,?) "
                    "ON CONFLICT(user_id,word) DO UPDATE SET category=excluded.category",
                    (user_id, word, values["category"]),
                )
    return web.json_response({"ok": True})


async def api_app_add(request: web.Request):
    user_id = await require_app_user(request)
    try:
        data = await request.json()
    except (json.JSONDecodeError, web.HTTPBadRequest):
        return web.json_response({"ok": False, "error": "Некорректный JSON"}, status=400)

    text = str(data.get("text", "")).strip()
    if text:
        items = await parse_text(text, user_id)
        if not items:
            return web.json_response({"ok": False, "error": "Не нашёл сумму. Например: «кофе 250»."}, status=400)
        needs_confirmation = any(item["category"] == "Другое" for item in items)
        if needs_confirmation:
            return web.json_response({"ok": True, "confirmed": False, "items": items})
        reply = save_parsed_items(user_id, items)
        warnings = [line for line in reply.splitlines() if line.startswith(("⚠️", "🚨", "🔴"))]
        if warnings:
            try:
                await bot.send_message(user_id, "\n".join(warnings))
            except Exception:
                log.exception("Cannot notify user about a budget from Mini App")
        return web.json_response({"ok": True, "confirmed": True, "reply": reply})

    submitted_items = data.get("items")
    if submitted_items is not None:
        if not isinstance(submitted_items, list) or not submitted_items or len(submitted_items) > 20:
            return web.json_response({"ok": False, "error": "Некорректный список операций"}, status=400)
        items = []
        for item in submitted_items:
            if not isinstance(item, dict):
                return web.json_response({"ok": False, "error": "Некорректная операция"}, status=400)
            item_kind = item.get("kind")
            category_list = INCOME_CATS if item_kind == "income" else EXPENSE_CATS
            try:
                item_amount = float(str(item.get("amount", "")).replace(" ", "").replace(",", "."))
            except (TypeError, ValueError):
                item_amount = 0
            if item_kind not in {"income", "expense"} or item.get("category") not in category_list:
                return web.json_response({"ok": False, "error": "Проверьте тип и категорию каждой операции"}, status=400)
            if not math.isfinite(item_amount) or item_amount <= 0:
                return web.json_response({"ok": False, "error": "Сумма должна быть больше нуля"}, status=400)
            items.append({
                "kind": item_kind,
                "amount": round(item_amount, 2),
                "category": item["category"],
                "note": str(item.get("note", "")).strip()[:100],
            })
        reply = save_parsed_items(user_id, items)
        with db() as c:
            for source, parsed in zip(submitted_items, items):
                if source.get("uncertain") and parsed["kind"] == "expense":
                    for word in {norm(token) for token in _tokens(parsed["note"]) if len(token) >= 3}:
                        c.execute(
                            "INSERT INTO rules(user_id,word,category) VALUES (?,?,?) "
                            "ON CONFLICT(user_id,word) DO UPDATE SET category=excluded.category",
                            (user_id, word, parsed["category"]),
                        )
        warnings = [line for line in reply.splitlines() if line.startswith(("⚠️", "🚨", "🔴"))]
        if warnings:
            try:
                await bot.send_message(user_id, "\n".join(warnings))
            except Exception:
                log.exception("Cannot notify user about a budget from Mini App")
        return web.json_response({"ok": True, "confirmed": True, "reply": reply})

    kind = data.get("kind")
    category = data.get("category")
    categories = INCOME_CATS if kind == "income" else EXPENSE_CATS
    try:
        amount = float(str(data.get("amount", "")).replace(" ", "").replace(",", "."))
    except ValueError:
        amount = 0
    if kind not in {"income", "expense"} or category not in categories:
        return web.json_response({"ok": False, "error": "Выберите тип и категорию"}, status=400)
    if not math.isfinite(amount) or amount <= 0:
        return web.json_response({"ok": False, "error": "Укажите сумму больше нуля"}, status=400)

    note = str(data.get("note", "")).strip()[:100]
    created_at = datetime.now(timezone.utc)
    if data.get("datetime"):
        try:
            created_at = datetime.fromisoformat(str(data["datetime"]))
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=user_timezone(user_id))
            created_at = created_at.astimezone(timezone.utc)
        except ValueError:
            return web.json_response({"ok": False, "error": "Некорректная дата"}, status=400)
    with db() as c:
        c.execute(
            "INSERT INTO transactions(user_id,kind,amount,category,note,created_at) VALUES (?,?,?,?,?,?)",
            (user_id, kind, amount, category, note, created_at.isoformat()),
        )
    warnings = budget_warnings(user_id, [{"kind": kind, "category": category}])
    if warnings:
        try:
            await bot.send_message(user_id, "\n".join(warnings))
        except Exception:
            log.exception("Cannot notify user about a budget from Mini App")
    return web.json_response({"ok": True, "reply": "Записано", "warnings": warnings})


async def api_app_budgets(request: web.Request):
    user_id = await require_app_user(request)
    if request.method == "GET":
        with db() as c:
            rows = c.execute(
                "SELECT category, limit_amount FROM budgets WHERE user_id=? ORDER BY category",
                (user_id,),
            ).fetchall()
            items = []
            for row in rows:
                spent = month_spent(c, user_id, row["category"])
                limit = row["limit_amount"]
                items.append({
                    "category": row["category"],
                    "spent": spent,
                    "limit": limit,
                    "pct": round(spent / limit * 100),
                    "spent_text": money(spent),
                    "limit_text": money(limit),
                })
        return web.json_response({"ok": True, "items": items})

    try:
        data = await request.json()
        category = data.get("category")
        limit = float(str(data.get("limit", "")).replace(" ", "").replace(",", "."))
    except (json.JSONDecodeError, web.HTTPBadRequest, TypeError, ValueError):
        return web.json_response({"ok": False, "error": "Проверьте категорию и сумму лимита"}, status=400)
    if category not in EXPENSE_CATS or not math.isfinite(limit) or limit < 0:
        return web.json_response({"ok": False, "error": "Проверьте категорию и сумму лимита"}, status=400)
    with db() as c:
        if limit == 0:
            c.execute("DELETE FROM budgets WHERE user_id=? AND category=?", (user_id, category))
        else:
            c.execute(
                "INSERT INTO budgets(user_id,category,limit_amount) VALUES (?,?,?) "
                "ON CONFLICT(user_id,category) DO UPDATE SET limit_amount=excluded.limit_amount",
                (user_id, category, limit),
            )
    return web.json_response({"ok": True})


async def api_app_goals(request: web.Request):
    user_id = await require_app_user(request)
    if request.method == "GET":
        with db() as c:
            rows = c.execute(
                "SELECT id, title, target_amount, icon, saved_amount FROM goals "
                "WHERE user_id=? ORDER BY id DESC",
                (user_id,),
            ).fetchall()
        items = [{
            "id": row["id"],
            "title": row["title"],
            "icon": row["icon"],
            "target": row["target_amount"],
            "saved": row["saved_amount"],
            "pct": min(100, round(row["saved_amount"] / row["target_amount"] * 100)),
        } for row in rows]
        return web.json_response({"ok": True, "items": items})

    try:
        data = await request.json()
        title = str(data.get("title", "")).strip()[:60]
        target = float(str(data.get("target", "")).replace(" ", "").replace(",", "."))
        initial = float(str(data.get("initial", "0")).replace(" ", "").replace(",", "."))
        icon = str(data.get("icon", "🎯"))[:8]
    except (json.JSONDecodeError, web.HTTPBadRequest, TypeError, ValueError):
        return web.json_response({"ok": False, "error": "Укажите название и сумму цели"}, status=400)
    if not title or not math.isfinite(target) or target <= 0 or not math.isfinite(initial) or initial < 0:
        return web.json_response({"ok": False, "error": "Укажите название и сумму цели больше нуля"}, status=400)
    with db() as c:
        cur = c.execute(
            "INSERT INTO goals(user_id,title,target_amount,icon,saved_amount,created_at) VALUES (?,?,?,?,?,?) RETURNING id",
            (user_id, title, target, icon, initial, datetime.now(timezone.utc).isoformat()),
        )
        goal_id = cur.fetchone()["id"]
    return web.json_response({"ok": True, "id": goal_id})


async def api_app_goal_add(request: web.Request):
    user_id = await require_app_user(request)
    try:
        data = await request.json()
        amount = float(str(data.get("amount", "")).replace(" ", "").replace(",", "."))
    except (json.JSONDecodeError, web.HTTPBadRequest, TypeError, ValueError):
        amount = 0
    if not math.isfinite(amount) or amount <= 0:
        return web.json_response({"ok": False, "error": "Укажите сумму больше нуля"}, status=400)
    with db() as c:
        cur = c.execute(
            "UPDATE goals SET saved_amount=saved_amount+? WHERE id=? AND user_id=?",
            (amount, int(request.match_info["goal_id"]), user_id),
        )
    if not cur.rowcount:
        return web.json_response({"ok": False, "error": "Цель не найдена"}, status=404)
    return web.json_response({"ok": True})


async def api_app_goal_delete(request: web.Request):
    user_id = await require_app_user(request)
    with db() as c:
        cur = c.execute(
            "DELETE FROM goals WHERE id=? AND user_id=?",
            (int(request.match_info["goal_id"]), user_id),
        )
    if not cur.rowcount:
        return web.json_response({"ok": False, "error": "Цель не найдена"}, status=404)
    return web.json_response({"ok": True})


async def health(_request: web.Request):
    return web.Response(text="ok")


def create_web_app() -> web.Application:
    app = web.Application()
    app.router.add_post("/api/add", api_add)
    app.router.add_get("/app", app_index)
    app.router.add_get("/assets/app.js", app_script)
    app.router.add_get("/api/app/me", api_app_me)
    app.router.add_get("/api/app/stats", api_app_stats)
    app.router.add_get("/api/app/transactions", api_app_transactions)
    app.router.add_patch(r"/api/app/transactions/{tx_id:\d+}", api_app_update_transaction)
    app.router.add_delete(r"/api/app/transactions/{tx_id:\d+}", api_app_delete_transaction)
    app.router.add_post(r"/api/app/transactions/{tx_id:\d+}/restore", api_app_restore_transaction)
    app.router.add_post("/api/app/add", api_app_add)
    app.router.add_route("GET", "/api/app/budgets", api_app_budgets)
    app.router.add_route("POST", "/api/app/budgets", api_app_budgets)
    app.router.add_route("GET", "/api/app/goals", api_app_goals)
    app.router.add_route("POST", "/api/app/goals", api_app_goals)
    app.router.add_post(r"/api/app/goals/{goal_id:\d+}/add", api_app_goal_add)
    app.router.add_delete(r"/api/app/goals/{goal_id:\d+}", api_app_goal_delete)
    app.router.add_route("GET", "/api/app/settings", api_app_settings)
    app.router.add_route("POST", "/api/app/settings", api_app_settings)
    app.router.add_get("/api/app/export", api_app_export)
    app.router.add_delete("/api/app/data", api_app_delete_data)
    app.router.add_get("/", health)
    return app


async def main():
    init_db()
    dp.message.filter(lambda m: m.from_user is not None and allowed(m.from_user.id))
    await bot.set_my_commands([
        BotCommand(command="start", description="Открыть главное меню"),
        BotCommand(command="today", description="Сводка за сегодня"),
        BotCommand(command="week", description="Сводка за неделю"),
        BotCommand(command="month", description="Сводка за месяц"),
        BotCommand(command="year", description="Сводка за год"),
        BotCommand(command="last", description="Последние операции"),
        BotCommand(command="budgets", description="Текущие бюджеты"),
        BotCommand(command="export", description="Скачать Excel"),
        BotCommand(command="admin", description="Сводка администратора"),
        BotCommand(command="help", description="Справка"),
    ])
    if PUBLIC_URL:
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(text="Мои финансы", web_app=WebAppInfo(url=app_url()))
        )
    else:
        await bot.set_chat_menu_button(menu_button=MenuButtonDefault())
    app = create_web_app()
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    log.info("Web server on port %s", PORT)
    await bot.delete_webhook(drop_pending_updates=True)
    summary_task = asyncio.create_task(weekly_summary_loop())
    try:
        await dp.start_polling(bot)
    finally:
        summary_task.cancel()
        await asyncio.gather(summary_task, return_exceptions=True)
        close_postgres_pool()


if __name__ == "__main__":
    asyncio.run(main())
