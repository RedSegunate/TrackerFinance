"""
Личный финансовый Telegram-бот.
- Пишете "вода 50" в чат или диктуете через iPhone-команду -> бот сам выбирает категорию.
- Статистика, бюджеты по категориям, экспорт в Excel.
Только рубли.
"""
import asyncio
import io
import json
import logging
import os
import re
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandObject
from aiogram.types import BufferedInputFile, Message
from aiohttp import web
from openpyxl import Workbook

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("finance-bot")

# ---------- Настройки (берутся из переменных окружения) ----------
BOT_TOKEN = os.environ["BOT_TOKEN"]
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")  # необязательно: без ключа бот работает по словарю
DB_PATH = os.getenv("DB_PATH", "finance.db")
PORT = int(os.getenv("PORT", "8080"))
PUBLIC_URL = os.getenv("PUBLIC_URL", "").rstrip("/")
TZ = ZoneInfo(os.getenv("TIMEZONE", "Europe/Moscow"))
MODEL = os.getenv("CLAUDE_MODEL", "claude-haiku-5-5")
# Необязательно: список Telegram ID, которым разрешено пользоваться ботом (через запятую)
ALLOWED_USERS = {int(x) for x in os.getenv("ALLOWED_USERS", "").replace(" ", "").split(",") if x}

EXPENSE_CATS = [
    "Продукты", "Кафе и рестораны", "Транспорт", "Авто", "Жильё", "Связь и интернет",
    "Здоровье", "Одежда", "Красота", "Развлечения", "Подписки", "Образование",
    "Семья и дети", "Подарки", "Путешествия", "Бизнес-расходы", "Другое",
]
INCOME_CATS = ["Зарплата", "Подработка", "Бизнес", "Подарок", "Другое"]

bot = Bot(BOT_TOKEN)
dp = Dispatcher()
claude = None
if ANTHROPIC_API_KEY:
    from anthropic import AsyncAnthropic
    claude = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)


# ---------- База данных ----------
@contextmanager
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    with db() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                token TEXT UNIQUE NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                kind TEXT NOT NULL,
                amount REAL NOT NULL,
                category TEXT NOT NULL,
                note TEXT,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_tx_user_date ON transactions(user_id, created_at);
            CREATE TABLE IF NOT EXISTS budgets (
                user_id INTEGER NOT NULL,
                category TEXT NOT NULL,
                limit_amount REAL NOT NULL,
                PRIMARY KEY (user_id, category)
            );
            CREATE TABLE IF NOT EXISTS rules (
                user_id INTEGER NOT NULL,
                word TEXT NOT NULL,
                category TEXT NOT NULL,
                PRIMARY KEY (user_id, word)
            );
            """
        )


def allowed(user_id: int) -> bool:
    return not ALLOWED_USERS or user_id in ALLOWED_USERS


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


def period_start(name: str) -> str:
    now = datetime.now(TZ)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if name == "today":
        start = midnight
    elif name == "week":
        start = midnight - timedelta(days=midnight.weekday())
    else:
        start = midnight.replace(day=1)
    return start.astimezone(timezone.utc).isoformat()


def local_dt(iso: str) -> datetime:
    return datetime.fromisoformat(iso).astimezone(TZ)


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
        "SELECT COALESCE(SUM(amount),0) FROM transactions "
        "WHERE user_id=? AND kind='expense' AND category=? AND created_at>=?",
        (user_id, category, period_start("month")),
    ).fetchone()[0]


def budget_warnings(user_id: int, items):
    msgs, seen = [], set()
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
            if pct >= 100:
                msgs.append(f"🚨 Бюджет «{cat}» превышен: {money(spent)} из {money(lim)}")
            elif pct >= 80:
                msgs.append(f"⚠️ Бюджет «{cat}»: использовано {pct:.0f}% ({money(spent)} из {money(lim)})")
    return msgs


async def process_text(user_id: int, text: str) -> str:
    items = await parse_text(text, user_id)
    if not items:
        return "Не нашёл сумму. Напишите, например: «вода 50» или «зарплата 80000»."
    now = datetime.now(timezone.utc).isoformat()
    lines = []
    with db() as c:
        for it in items:
            cur = c.execute(
                "INSERT INTO transactions(user_id,kind,amount,category,note,created_at) VALUES (?,?,?,?,?,?)",
                (user_id, it["kind"], it["amount"], it["category"], it["note"], now),
            )
            label = "Расход" if it["kind"] == "expense" else "Доход"
            sign = "−" if it["kind"] == "expense" else "+"
            note = f" · {it['note']}" if it["note"] else ""
            lines.append(f"✅ {label}: {sign}{money(it['amount'])} · {it['category']}{note}  (отмена: /del {cur.lastrowid})")
            if it["kind"] == "expense" and it["category"] == "Другое":
                lines.append(f"❓ Категория не определена. Выберите: /cat {cur.lastrowid} Продукты (любая из /categories), и я запомню слово.")
    lines += budget_warnings(user_id, items)
    return "\n".join(lines)


def stats_text(user_id: int, period: str) -> str:
    titles = {"today": "Сегодня", "week": "Эта неделя", "month": "Этот месяц"}
    since = period_start(period)
    with db() as c:
        def total(kind):
            return c.execute(
                "SELECT COALESCE(SUM(amount),0) FROM transactions WHERE user_id=? AND kind=? AND created_at>=?",
                (user_id, kind, since),
            ).fetchone()[0]
        inc, exp = total("income"), total("expense")
        cats = c.execute(
            "SELECT category, SUM(amount) s FROM transactions "
            "WHERE user_id=? AND kind='expense' AND created_at>=? GROUP BY category ORDER BY s DESC",
            (user_id, since),
        ).fetchall()
    out = [f"📊 {titles[period]}", f"Доходы: +{money(inc)}", f"Расходы: −{money(exp)}", f"Баланс: {money(inc - exp)}"]
    if cats:
        out.append("\nРасходы по категориям:")
        for r in cats:
            share = r["s"] / exp * 100 if exp else 0
            out.append(f"• {r['category']}: {money(r['s'])} ({share:.0f}%)")
    else:
        out.append("\nЗаписей пока нет.")
    return "\n".join(out)


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
        ws.append([r["id"], local_dt(r["created_at"]).strftime("%Y-%m-%d %H:%M"), kind,
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

Просто пишите как удобно:
• вода 50
• такси 350 и кофе 200
• зарплата 80000

Команды:
/today /week /month — статистика
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
    ensure_user(m.from_user.id)
    await m.answer("Привет! 👋\n\n" + HELP)


@dp.message(Command("today"))
async def cmd_today(m: Message):
    await m.answer(stats_text(m.from_user.id, "today"))


@dp.message(Command("week"))
async def cmd_week(m: Message):
    await m.answer(stats_text(m.from_user.id, "week"))


@dp.message(Command("month"))
async def cmd_month(m: Message):
    await m.answer(stats_text(m.from_user.id, "month"))


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
        lines.append(f"#{r['id']} {local_dt(r['created_at']).strftime('%d.%m %H:%M')} "
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
    await m.answer(await process_text(m.from_user.id, m.text))


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


async def health(_request: web.Request):
    return web.Response(text="ok")


async def main():
    init_db()
    dp.message.filter(lambda m: m.from_user is not None and allowed(m.from_user.id))
    app = web.Application()
    app.router.add_post("/api/add", api_add)
    app.router.add_get("/", health)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    log.info("Web server on port %s", PORT)
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
