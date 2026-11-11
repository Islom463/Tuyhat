# -*- coding: utf-8 -*-
"""
TAKLIFNOMA BOT — AI video taklifnoma, tarjima va grammatika tekshiruvi (Telegram, aiogram 3).

Render'da Start Command: python main.py

Muhit o'zgaruvchilari (Render → Environment):
  BOT_TOKEN        - BotFather tokeni (majburiy)
  ADMIN_ID         - admin Telegram ID (bir nechta bo'lsa vergul bilan). To'lov cheklari va zaxira shu yerga keladi
  GROQ_API_KEY     - console.groq.com dan olingan kalit (gsk_...). AI shu bilan ishlaydi
  PRICE            - ixtiyoriy: obuna narxi, standart 500000
  ACCESS_DAYS      - ixtiyoriy: obuna muddati (kun). 0 = muddatsiz (standart)
  FREE_DAILY       - ixtiyoriy: to'lamagan foydalanuvchiga kuniga nechta bepul tarjima/tekshiruv (standart 8, 0 = o'chiq)
  CARD_NUMBER / CARD_OWNER / ADMIN_CONTACT - ixtiyoriy: karta raqami, egasi va admin username
  GROQ_MODEL / GROQ_VISION_MODEL - ixtiyoriy: model nomlarini majburan belgilash
  BACKUP_MINUTES   - ixtiyoriy: avtomatik zaxira oralig'i (daqiqa), standart 30
"""
import asyncio
import base64
import hashlib
import html
import io
import json
import logging
import os
import random
import re
import shutil
import sqlite3
import tempfile
import threading
import time
import urllib.request
from contextlib import closing
from datetime import datetime, timezone

import aiohttp
from aiohttp import web
from aiogram import Bot, Dispatcher, F, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramUnauthorizedError
from aiogram.filters import Command, CommandObject, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (BufferedInputFile, ErrorEvent, FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup,
                           InputMediaDocument, KeyboardButton, ReplyKeyboardMarkup)

import studio
from texts import LANG_NAMES, LANGS, PALETTE_LABELS, S, TR_LANGS, to_cyrillic, to_latin
from texts import tr as _tr

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
BOT_STATUS = {"text": "Bot ishga tushmoqda..."}

# ============================================================================================
# Sozlamalar
# ============================================================================================
DB_PATH = os.getenv("DB_PATH", "taklifnoma.db")
os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)


def _int_env(name, default):
    try:
        return int(re.sub(r"[^\d]", "", os.getenv(name, "")) or default)
    except ValueError:
        return default


ADMIN_IDS = {int(x) for x in re.findall(r"\d+", os.getenv("ADMIN_ID", "") + " " + os.getenv("ADMIN_IDS", ""))}
PRICE = _int_env("PRICE", 500000)
ACCESS_DAYS = _int_env("ACCESS_DAYS", 0)
FREE_DAILY = _int_env("FREE_DAILY", 8)
CARD_NUMBER = os.getenv("CARD_NUMBER", "5614 6818 7058 8666").strip()
CARD_OWNER = os.getenv("CARD_OWNER", "Panjiyev Islom").strip()
ADMIN_CONTACT = os.getenv("ADMIN_CONTACT", "@Panjiyev04").strip()
try:
    BACKUP_MINUTES = float(os.getenv("BACKUP_MINUTES", "30"))
except ValueError:
    BACKUP_MINUTES = 30.0
LIFETIME = 4102444800  # 2100-01-01 — "muddatsiz" belgisi


def detect_token():
    tok_re = r"\d{6,}:[A-Za-z0-9_-]{30,}"
    env = {k: (v or "").strip().strip('"').strip("'") for k, v in os.environ.items()}
    for k in ("BOT_TOKEN", "TELEGRAM_BOT_TOKEN", "TOKEN"):
        m = re.search(tok_re, env.get(k, ""))
        if m:
            return m.group(0)
    for v in env.values():
        m = re.search(tok_re, v)
        if m:
            return m.group(0)
    return ""


def detect_groq_key():
    env = {k: (v or "").strip().strip('"').strip("'") for k, v in os.environ.items()}
    for k in ("GROQ_API_KEY", "GROQ_KEY", "GROQ_TOKEN", "GROQ"):
        v = env.get(k, "")
        if v.lower().startswith("bearer "):
            v = v[7:].strip()
        m = re.search(r"gsk_[A-Za-z0-9]+", v)
        if m:
            return m.group(0)
        if v and " " not in v:
            return v
    for v in env.values():
        m = re.search(r"gsk_[A-Za-z0-9]{20,}", v)
        if m:
            return m.group(0)
    return ""


TOKEN = detect_token()
if not TOKEN:
    while True:
        logging.error("BOT_TOKEN topilmadi! Render Environment'ga BOT_TOKEN ni kiriting.")
        time.sleep(30)
GROQ_KEY = detect_groq_key()

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

_BG_TASKS = set()


def run_bg(coro):
    t = asyncio.create_task(coro)
    _BG_TASKS.add(t)
    t.add_done_callback(_BG_TASKS.discard)
    return t


def esc(s):
    return html.escape(str(s), quote=False)


# ============================================================================================
# Render uchun veb-server va keep-alive
# ============================================================================================
async def _root_handler(request):
    return web.Response(text=BOT_STATUS["text"])


async def start_web_server():
    app = web.Application()
    app.add_routes([web.get("/", _root_handler), web.get("/ping", _root_handler)])
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", int(os.getenv("PORT", 8080))).start()
    logging.info("Veb-server ishga tushdi (port %s)", os.getenv("PORT", 8080))


def self_ping():
    while True:
        time.sleep(240)
        try:
            url = os.getenv("RENDER_EXTERNAL_URL") or f"http://127.0.0.1:{os.environ.get('PORT', 8080)}"
            urllib.request.urlopen(url, timeout=20).read()
        except Exception:
            pass


class _StatusLogHandler(logging.Handler):
    def emit(self, record):
        try:
            msg = record.getMessage()
        except Exception:
            return
        stamp = time.strftime("%H:%M:%S", time.gmtime())
        if "TelegramConflictError" in msg or "terminated by other getUpdates" in msg:
            BOT_STATUS["text"] = (f"XATO (Conflict, {stamp} UTC): bu token boshqa joyda ham ishlayapti. "
                                  "Eski xizmat yoki nusxani to'xtating.")
        elif "TelegramUnauthorizedError" in msg:
            BOT_STATUS["text"] = f"XATO (Unauthorized, {stamp} UTC): Telegram tokenni qabul qilmadi."


logging.getLogger("aiogram").addHandler(_StatusLogHandler())


async def wait_for_valid_token():
    while True:
        try:
            me = await bot.get_me()
            BOT_STATUS["text"] = f"OK: @{me.username} ishlayapti"
            logging.info("Bot ulandi: @%s", me.username)
            return
        except TelegramUnauthorizedError:
            BOT_STATUS["text"] = "XATO: Telegram tokenni qabul qilmadi (Unauthorized). BOT_TOKEN ni tekshiring."
            logging.error(BOT_STATUS["text"])
        except Exception as ex:
            BOT_STATUS["text"] = f"Telegramga ulanib bo'lmadi ({type(ex).__name__}). Qayta urinilmoqda..."
            logging.error("%s: %s", BOT_STATUS["text"], ex)
        await asyncio.sleep(60)


# ============================================================================================
# Baza
# ============================================================================================
def db():
    return closing(sqlite3.connect(DB_PATH, timeout=30))


def init_db():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, name TEXT, username TEXT, lang TEXT,
            joined INTEGER, paid_until INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS payments (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, status TEXT,
            file_id TEXT, ftype TEXT, created INTEGER, decided INTEGER, admin_id INTEGER, amount INTEGER);
        CREATE TABLE IF NOT EXISTS usage (user_id INTEGER, day TEXT, cnt INTEGER DEFAULT 0, PRIMARY KEY (user_id, day));
        CREATE TABLE IF NOT EXISTS music (id INTEGER PRIMARY KEY AUTOINCREMENT, file_id TEXT, title TEXT, added INTEGER);
        CREATE TABLE IF NOT EXISTS orders (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, created INTEGER, lang TEXT);
        """)
        c.commit()


init_db()


def is_admin(uid):
    return uid in ADMIN_IDS


_LANG = {}


def get_lang(uid):
    if uid in _LANG:
        return _LANG[uid]
    with db() as c:
        row = c.execute("SELECT lang FROM users WHERE user_id = ?", (uid,)).fetchone()
    lang = row[0] if row and row[0] in LANGS else None
    if lang:
        _LANG[uid] = lang
    return lang


def set_lang(uid, lang):
    with db() as c:
        c.execute("UPDATE users SET lang = ? WHERE user_id = ?", (lang, uid))
        c.commit()
    _LANG[uid] = lang


def upsert_user(u):
    name = (u.full_name or u.first_name or "")[:80]
    with db() as c:
        c.execute("INSERT OR IGNORE INTO users (user_id, name, username, joined) VALUES (?, ?, ?, ?)",
                  (u.id, name, u.username or "", int(time.time())))
        c.execute("UPDATE users SET name = ?, username = ? WHERE user_id = ?", (name, u.username or "", u.id))
        c.commit()


def paid_until(uid):
    with db() as c:
        row = c.execute("SELECT paid_until FROM users WHERE user_id = ?", (uid,)).fetchone()
    return int(row[0] or 0) if row else 0


def has_access(uid):
    return is_admin(uid) or paid_until(uid) > time.time()


def grant_access(uid, days=None):
    days = ACCESS_DAYS if days is None else days
    now = int(time.time())
    if days <= 0:
        new = LIFETIME
    else:
        new = max(now, paid_until(uid)) + days * 86400
        new = min(new, LIFETIME)
    with db() as c:
        c.execute("INSERT OR IGNORE INTO users (user_id, name, username, joined) VALUES (?, '', '', ?)", (uid, now))
        c.execute("UPDATE users SET paid_until = ? WHERE user_id = ?", (new, uid))
        c.commit()
    return new


def revoke_access(uid):
    with db() as c:
        c.execute("UPDATE users SET paid_until = 0 WHERE user_id = ?", (uid,))
        c.commit()


def until_text(uid):
    p = paid_until(uid)
    if is_admin(uid) or p >= LIFETIME:
        return T(uid, "sub_life")
    return datetime.fromtimestamp(p, timezone.utc).strftime("%d.%m.%Y")


# kunlik bepul limit (tarjima / xato tekshirish)
def _today():
    return time.strftime("%Y-%m-%d", time.gmtime())


def quota_used(uid):
    with db() as c:
        row = c.execute("SELECT cnt FROM usage WHERE user_id = ? AND day = ?", (uid, _today())).fetchone()
    return int(row[0]) if row else 0


def quota_ok(uid):
    return has_access(uid) or quota_used(uid) < FREE_DAILY


def quota_use(uid):
    if has_access(uid):
        return
    with db() as c:
        c.execute("INSERT INTO usage (user_id, day, cnt) VALUES (?, ?, 1) "
                  "ON CONFLICT(user_id, day) DO UPDATE SET cnt = cnt + 1", (uid, _today()))
        c.commit()


# ============================================================================================
# Matn yordamchilari va klaviaturalar
# ============================================================================================
def T(uid, key, /, **kw):
    return _tr(get_lang(uid) or "uz", key, **kw)


def btn(text, data=None, url=None):
    return InlineKeyboardButton(text=text, callback_data=data) if data else InlineKeyboardButton(text=text, url=url)


def ikb(rows):
    return InlineKeyboardMarkup(inline_keyboard=rows)


def money(n):
    return f"{n:,}".replace(",", " ")


LABEL2ACT = {}
for _lang in LANGS:
    for _act in ("invite", "tr", "gr", "pay", "lang", "help"):
        LABEL2ACT[S[_lang]["m_" + _act]] = _act


def menu_kb(lang):
    t = lambda k: S[lang]["m_" + k]
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text=t("invite"))],
        [KeyboardButton(text=t("tr")), KeyboardButton(text=t("gr"))],
        [KeyboardButton(text=t("pay")), KeyboardButton(text=t("lang")), KeyboardButton(text=t("help"))],
    ], resize_keyboard=True)


def lang_kb():
    return ikb([[btn(LANG_NAMES["uz"], "lang:uz"), btn(LANG_NAMES["uz_cyrl"], "lang:uz_cyrl")],
                [btn(LANG_NAMES["ru"], "lang:ru"), btn(LANG_NAMES["en"], "lang:en")]])


LANG_PICK_TEXT = "🌍 Tilni tanlang · Тилни танланг · Выберите язык · Choose language"


async def send_long(chat_id, text, **kw):
    """Telegram 4096 belgi limiti uchun bo'lib yuboradi."""
    parts, cur = [], ""
    for line in text.split("\n"):
        if len(cur) + len(line) + 1 > 3800:
            parts.append(cur)
            cur = ""
        cur += line + "\n"
    if cur.strip():
        parts.append(cur)
    msg = None
    for i, p in enumerate(parts or [text]):
        msg = await bot.send_message(chat_id, p.rstrip("\n"), **(kw if i == len(parts) - 1 else {}))
    return msg


def pay_info_text(uid):
    period = T(uid, "period_life") if ACCESS_DAYS <= 0 else T(uid, "period_days", d=ACCESS_DAYS)
    return T(uid, "pay_info", price=money(PRICE), period=period, card=esc(CARD_NUMBER), owner=esc(CARD_OWNER),
             admin=esc(ADMIN_CONTACT))


def admin_url():
    return "https://t.me/" + ADMIN_CONTACT.lstrip("@")


def pay_kb(uid):
    return ikb([[btn(T(uid, "pay_send"), "pay:send")],
                [btn(T(uid, "pay_demo"), "pay:demo")],
                [btn(T(uid, "pay_admin"), url=admin_url())]])


# ============================================================================================
# Groq AI (tez va "qotib qolmaydigan": qisqa timeout, zaxira modellar, umumiy muddat)
# ============================================================================================
class AIError(Exception):
    pass


GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


def _models(*names):
    out = []
    for n in names:
        n = (n or "").strip()
        if n and n not in out:
            out.append(n)
    return out


TEXT_MODELS = _models(os.getenv("GROQ_MODEL", ""), "openai/gpt-oss-20b", "openai/gpt-oss-120b", "qwen/qwen3.6-27b")
VISION_MODELS = _models(os.getenv("GROQ_VISION_MODEL", ""), "qwen/qwen3.6-27b", "qwen/qwen3.8-27b",
                        "meta-llama/llama-4-scout-17b-16e-instruct")
_http = None
_ai_sem = None


async def http():
    global _http
    if _http is None or _http.closed:
        _http = aiohttp.ClientSession()
    return _http


def _extras(model):
    if model.startswith("openai/gpt-oss"):
        return {"reasoning_effort": "low"}
    if model.startswith("qwen/qwen3"):
        return {"reasoning_effort": "none"}
    return {}


def _clean_ai(text):
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)
    return text.strip()


async def groq_chat(messages, models=None, max_tokens=1500, temperature=0.3, deadline=50):
    """Modellarni ketma-ket sinaydi. Har bir urinish ≤25 s, umumiy ≤ deadline s — bot hech qachon osilib qolmaydi."""
    if not GROQ_KEY:
        raise AIError("GROQ_API_KEY topilmadi")
    models = models or TEXT_MODELS
    headers = {"Authorization": f"Bearer {GROQ_KEY}", "Content-Type": "application/json"}
    t_end = time.monotonic() + deadline
    last = "noma'lum xato"
    async with _ai_sem:
        session = await http()
        for model in models:
            use_extras = True
            for attempt in range(2):
                left = t_end - time.monotonic()
                if left < 4:
                    raise AIError("vaqt tugadi: " + last)
                payload = {"model": model, "messages": messages, "temperature": temperature,
                           "max_completion_tokens": max_tokens}
                if use_extras:
                    payload.update(_extras(model))
                try:
                    async with session.post(GROQ_URL, json=payload, headers=headers,
                                            timeout=aiohttp.ClientTimeout(total=min(25, left))) as r:
                        body = await r.text()
                        if r.status == 200:
                            data = json.loads(body)
                            out = _clean_ai(data["choices"][0]["message"].get("content"))
                            if out:
                                return out
                            last = f"{model}: bo'sh javob"
                            break
                        last = f"{model}: HTTP {r.status} {body[:160]}"
                        logging.warning("Groq %s", last)
                        if r.status in (401, 403):
                            raise AIError("Groq kaliti noto'g'ri yoki ruxsat yo'q (HTTP %s)" % r.status)
                        if r.status == 400 and use_extras and _extras(model):
                            use_extras = False          # model qo'shimcha parametrni tanimadi — qayta urinamiz
                            continue
                        if r.status == 429:
                            await asyncio.sleep(min(float(r.headers.get("retry-after", "1") or 1), 2.5))
                            if attempt == 0:
                                continue
                        break
                except asyncio.TimeoutError:
                    last = f"{model}: javob kechikdi"
                    logging.warning("Groq %s", last)
                    break
                except aiohttp.ClientError as ex:
                    last = f"{model}: tarmoq xatosi {type(ex).__name__}"
                    logging.warning("Groq %s", last)
                    break
    raise AIError(last)


def parse_json(text):
    text = re.sub(r"```(?:json)?", "", text or "").strip()
    i, j = text.find("{"), text.rfind("}")
    if i < 0 or j <= i:
        return None
    try:
        return json.loads(text[i:j + 1])
    except Exception:
        return None


LANG_DESC = {k: v[1] for k, v in TR_LANGS.items()}
DEFAULT_TEXT = {
    "uz": "Sizni farzandlarimizning nikoh to'yiga taklif etamiz",
    "uz_cyrl": to_cyrillic("Sizni farzandlarimizning nikoh to'yiga taklif etamiz"),
    "ru": "Приглашаем вас на свадьбу наших детей",
    "en": "We joyfully invite you to celebrate the wedding of our children",
}


async def ai_invite_text(names, lang):
    target = LANG_DESC["uz" if lang == "uz_cyrl" else lang]
    msgs = [{"role": "system", "content": "You write short, elegant, warm wedding invitation texts."},
            {"role": "user", "content": (
                f"Write a wedding invitation text in {target}, 2 short sentences, at most 150 characters, "
                f"written from the parents' point of view (inviting guests to their children's wedding). "
                f"The couple: {names}. Do NOT include date, time, address or the names. "
                f"Output only the text, without quotes.")}]
    out = await groq_chat(msgs, max_tokens=500, temperature=0.8, deadline=30)
    out = out.strip().strip('"«»“”').strip()
    out = re.sub(r"\s+", " ", out)[:220]
    return to_cyrillic(out) if lang == "uz_cyrl" else out


async def ai_design(desc):
    msgs = [{"role": "system", "content": "You are a luxury wedding invitation art director. Reply with JSON only."},
            {"role": "user", "content": (
                f'Client wish: "{desc[:300]}"\n'
                'Return ONLY a JSON object: {"bg1":"#RRGGBB","bg2":"#RRGGBB","accent":"#RRGGBB","text":"#RRGGBB",'
                '"style":"mandala|suzani|arch|star|vine"}. bg1 = top background color, bg2 = bottom background color '
                '(same family, usually a bit darker), accent = ornament color (gold, silver, rose gold...), '
                'text = main text color with STRONG contrast against the background. '
                'Styles: mandala = corner flower mandalas, suzani = Uzbek suzani scallops and rosettes, '
                'arch = mihrab arch, star = islamic star pattern, vine = floral vines.')}]
    out = await groq_chat(msgs, max_tokens=400, temperature=0.5, deadline=25)
    data = parse_json(out)
    if not data:
        raise AIError("JSON topilmadi")
    hexre = re.compile(r"^#[0-9a-fA-F]{6}$")
    pal = {k: data.get(k) for k in ("bg1", "bg2", "accent", "text")}
    if not all(isinstance(v, str) and hexre.match(v) for v in (pal["bg1"], pal["bg2"], pal["accent"])):
        raise AIError("ranglar noto'g'ri")
    if not (isinstance(pal["text"], str) and hexre.match(pal["text"])):
        pal["text"] = None
    style = data.get("style") if data.get("style") in studio.STYLES else None
    return pal, style


async def ai_translate(text, target):
    msgs = [{"role": "system", "content": (
        "You are a professional translator. First silently fix obvious spelling and grammar mistakes in the source, "
        "then translate it faithfully, keeping meaning, tone, line breaks, names and numbers. "
        "Output ONLY the translation, with no comments or quotes.")},
        {"role": "user", "content": f"Translate into {LANG_DESC[target]}:\n\n{text}"}]
    out = await groq_chat(msgs, max_tokens=2000, temperature=0.2)
    return out


async def ai_grammar(text, ui_lang):
    expl = LANG_DESC["uz" if ui_lang == "uz_cyrl" else ui_lang]
    msgs = [{"role": "system", "content": (
        "You are a meticulous proofreader for Uzbek (Latin and Cyrillic), Russian and English. "
        "Find spelling, grammar, punctuation and style mistakes. Keep the original language and script. "
        "Do not change the meaning. Reply with JSON only.")},
        {"role": "user", "content": (
            f"Text:\n{text}\n\n"
            'Return ONLY JSON: {"corrected": "<full corrected text>", "errors": '
            '[{"wrong": "<fragment>", "right": "<fix>", "reason": "<short explanation>"}]}. '
            f"Write each reason in {expl}. If there are no mistakes, return the same text and an empty errors list.")}]
    out = await groq_chat(msgs, max_tokens=2500, temperature=0.1)
    data = parse_json(out)
    if not data or "corrected" not in data:
        return {"corrected": out.strip(), "errors": []}
    errs = [e for e in (data.get("errors") or []) if isinstance(e, dict) and e.get("wrong") and e.get("right")]
    return {"corrected": str(data["corrected"]).strip(), "errors": errs}


def _vision_msg(prompt, b64):
    return [{"role": "user", "content": [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + b64}}]}]


async def ai_vision_translate(b64, target):
    prompt = ("Read ALL text visible in this image exactly as written (OCR), keeping line breaks. "
              f"Then translate it into {LANG_DESC[target]} (silently fixing obvious mistakes). "
              'Return ONLY JSON: {"original": "<text from the image>", "translation": "<translation>"}. '
              'If there is no text, return {"original": "", "translation": ""}.')
    out = await groq_chat(_vision_msg(prompt, b64), models=VISION_MODELS, max_tokens=2500, temperature=0.1, deadline=55)
    data = parse_json(out)
    if not data:
        return {"original": "", "translation": out.strip()}
    return {"original": str(data.get("original") or "").strip(), "translation": str(data.get("translation") or "").strip()}


async def ai_vision_grammar(b64, ui_lang):
    expl = LANG_DESC["uz" if ui_lang == "uz_cyrl" else ui_lang]
    prompt = ("Read ALL text visible in this image exactly as written (OCR). Then find spelling, grammar and punctuation "
              "mistakes in it, keeping the original language and script. "
              'Return ONLY JSON: {"original": "<text>", "corrected": "<corrected text>", "errors": '
              '[{"wrong": "<fragment>", "right": "<fix>", "reason": "<short explanation>"}]}. '
              f"Write each reason in {expl}. If there is no text, return empty strings.")
    out = await groq_chat(_vision_msg(prompt, b64), models=VISION_MODELS, max_tokens=3000, temperature=0.1, deadline=55)
    data = parse_json(out)
    if not data:
        return {"original": "", "corrected": out.strip(), "errors": []}
    errs = [e for e in (data.get("errors") or []) if isinstance(e, dict) and e.get("wrong") and e.get("right")]
    return {"original": str(data.get("original") or "").strip(), "corrected": str(data.get("corrected") or "").strip(),
            "errors": errs}


def prepare_image_b64(raw):
    from PIL import Image, ImageOps
    im = Image.open(io.BytesIO(raw))
    im = ImageOps.exif_transpose(im).convert("RGB")
    im.thumbnail((1600, 1600))
    data = b""
    for q in (85, 75, 65, 50):
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=q, optimize=True)
        data = buf.getvalue()
        if len(data) < 2_800_000:
            break
    return base64.b64encode(data).decode()


async def get_image_b64(message):
    f = None
    if message.photo:
        f = message.photo[-1]
    elif message.document and (message.document.mime_type or "").startswith("image/"):
        f = message.document
    if f is None:
        return None
    buf = io.BytesIO()
    await bot.download(f, destination=buf)
    return await asyncio.to_thread(prepare_image_b64, buf.getvalue())


# ============================================================================================
# Holatlar (FSM)
# ============================================================================================
class Inv(StatesGroup):
    names = State()
    date = State()
    time = State()
    venue = State()
    lang = State()
    text = State()
    style = State()
    styletext = State()
    palette = State()
    music = State()
    musicfile = State()


class Pay(StatesGroup):
    receipt = State()


class Tr(StatesGroup):
    wait = State()


class Gr(StatesGroup):
    wait = State()


class AdmMusic(StatesGroup):
    add = State()


# ============================================================================================
# /start, til, menyu
# ============================================================================================
async def send_welcome(chat_id, uid, name):
    await bot.send_message(chat_id, T(uid, "welcome", name=esc(name or "")), reply_markup=menu_kb(get_lang(uid) or "uz"))


@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    uid = message.from_user.id
    upsert_user(message.from_user)
    if not get_lang(uid):
        return await message.answer(LANG_PICK_TEXT, reply_markup=lang_kb())
    await send_welcome(message.chat.id, uid, message.from_user.first_name)


@dp.callback_query(F.data.startswith("lang:"))
async def cb_lang(callback: types.CallbackQuery, state: FSMContext):
    lang = callback.data.split(":")[1]
    if lang not in LANGS:
        return await callback.answer()
    uid = callback.from_user.id
    first = not get_lang(uid)
    upsert_user(callback.from_user)
    set_lang(uid, lang)
    await state.clear()
    await callback.answer()
    try:
        await callback.message.delete()
    except Exception:
        pass
    if first:
        await send_welcome(callback.message.chat.id, uid, callback.from_user.first_name)
    else:
        await bot.send_message(callback.message.chat.id, T(uid, "lang_changed"), reply_markup=menu_kb(lang))
    run_bg(safe_push_backup())


@dp.message(Command("cancel"))
async def cmd_cancel(message: types.Message, state: FSMContext):
    await state.clear()
    uid = message.from_user.id
    await message.answer(T(uid, "cancelled"), reply_markup=menu_kb(get_lang(uid) or "uz"))


@dp.message(F.text.in_(set(LABEL2ACT)))
async def on_menu(message: types.Message, state: FSMContext):
    await state.clear()
    uid = message.from_user.id
    upsert_user(message.from_user)
    if not get_lang(uid):
        return await message.answer(LANG_PICK_TEXT, reply_markup=lang_kb())
    act = LABEL2ACT[message.text]
    if act == "lang":
        await message.answer(LANG_PICK_TEXT, reply_markup=lang_kb())
    elif act == "help":
        await message.answer(T(uid, "help", admin=esc(ADMIN_CONTACT)))
    elif act == "pay":
        await show_subscription(message.chat.id, uid)
    elif act == "invite":
        await begin_invite(message, state)
    elif act == "tr":
        await message.answer(T(uid, "tr_pick"), reply_markup=tr_lang_kb())
    elif act == "gr":
        await state.set_state(Gr.wait)
        await message.answer(T(uid, "gr_ready"))


# ============================================================================================
# To'lov va obuna
# ============================================================================================
async def show_subscription(chat_id, uid):
    if has_access(uid):
        await bot.send_message(chat_id, T(uid, "sub_active", until=until_text(uid)))
    else:
        await bot.send_message(chat_id, T(uid, "sub_none") + "\n\n" + pay_info_text(uid), reply_markup=pay_kb(uid))


def pending_payment(uid):
    with db() as c:
        return c.execute("SELECT id FROM payments WHERE user_id = ? AND status = 'pending'", (uid,)).fetchone()


@dp.callback_query(F.data == "pay:send")
async def cb_pay_send(callback: types.CallbackQuery, state: FSMContext):
    uid = callback.from_user.id
    await callback.answer()
    if has_access(uid):
        return await callback.message.answer(T(uid, "sub_active", until=until_text(uid)))
    if pending_payment(uid):
        return await callback.message.answer(T(uid, "pay_pending", admin=esc(ADMIN_CONTACT)))
    await state.set_state(Pay.receipt)
    await callback.message.answer(T(uid, "pay_receipt_prompt"))


@dp.message(Pay.receipt, F.photo | F.document)
async def pay_receipt(message: types.Message, state: FSMContext):
    uid = message.from_user.id
    if message.photo:
        file_id, ftype = message.photo[-1].file_id, "photo"
    else:
        file_id, ftype = message.document.file_id, "document"
    with db() as c:
        cur = c.execute("INSERT INTO payments (user_id, status, file_id, ftype, created, amount) VALUES (?, 'pending', ?, ?, ?, ?)",
                        (uid, file_id, ftype, int(time.time()), PRICE))
        pid = cur.lastrowid
        c.commit()
    await state.clear()
    await message.answer(T(uid, "pay_sent"), reply_markup=menu_kb(get_lang(uid) or "uz"))
    u = message.from_user
    caption = (f"💳 <b>Yangi to'lov #{pid}</b>\n👤 {esc(u.full_name)}"
               + (f" (@{esc(u.username)})" if u.username else "")
               + f"\n🆔 <code>{u.id}</code>\n💰 {money(PRICE)} so'm")
    kb = ikb([[btn("✅ Tasdiqlash", f"pay:ok:{pid}"), btn("❌ Rad etish", f"pay:no:{pid}")]])
    for aid in ADMIN_IDS:
        try:
            if ftype == "photo":
                await bot.send_photo(aid, file_id, caption=caption, reply_markup=kb)
            else:
                await bot.send_document(aid, file_id, caption=caption, reply_markup=kb)
        except Exception as ex:
            logging.warning("adminga chek yuborilmadi (%s): %s", aid, ex)
    run_bg(safe_push_backup())


@dp.message(Pay.receipt)
async def pay_receipt_other(message: types.Message):
    await message.answer(T(message.from_user.id, "pay_need_photo"))


@dp.callback_query(F.data.startswith("pay:ok:") | F.data.startswith("pay:no:"))
async def cb_pay_decide(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        return await callback.answer("⛔", show_alert=True)
    _, action, pid = callback.data.split(":")
    pid = int(pid)
    with db() as c:
        row = c.execute("SELECT user_id, status FROM payments WHERE id = ?", (pid,)).fetchone()
    if not row:
        return await callback.answer("Topilmadi", show_alert=True)
    uid, status = row
    if status != "pending":
        return await callback.answer("Bu to'lov allaqachon ko'rib chiqilgan.", show_alert=True)
    ok = action == "ok"
    with db() as c:
        c.execute("UPDATE payments SET status = ?, decided = ?, admin_id = ? WHERE id = ?",
                  ("approved" if ok else "rejected", int(time.time()), callback.from_user.id, pid))
        c.commit()
    if ok:
        grant_access(uid)
    await callback.answer("✅ Tasdiqlandi" if ok else "❌ Rad etildi")
    mark = "\n\n✅ <b>TASDIQLANDI</b>" if ok else "\n\n❌ <b>RAD ETILDI</b>"
    try:
        await callback.message.edit_caption(caption=(callback.message.caption or "") + mark, reply_markup=None)
    except Exception:
        pass
    try:
        await bot.send_message(uid, T(uid, "pay_ok" if ok else "pay_no", admin=esc(ADMIN_CONTACT)))
    except Exception as ex:
        logging.info("foydalanuvchiga xabar yuborilmadi: %s", ex)
    run_bg(safe_push_backup())


_demo_last = {}


@dp.callback_query(F.data == "pay:demo")
async def cb_pay_demo(callback: types.CallbackQuery):
    uid = callback.from_user.id
    await callback.answer()
    if time.time() - _demo_last.get(uid, 0) < 15:
        return
    _demo_last[uid] = time.time()
    lang = get_lang(uid) or "uz"
    demo_lang = "ru" if lang == "ru" else "en" if lang == "en" else lang
    sample = {
        "uz": ("Aziz va Madina", "15 dekabr, 2026", "18:00", "«Registon» to'yxonasi, Toshkent"),
        "uz_cyrl": ("Азиз ва Мадина", "15 декабр, 2026", "18:00", "«Регистон» тўйхонаси, Тошкент"),
        "ru": ("Азиз и Мадина", "15 декабря 2026", "18:00", "Банкетный зал «Регистан», Ташкент"),
        "en": ("Aziz & Madina", "15 December 2026", "6:00 PM", "Registan Hall, Tashkent"),
    }[demo_lang]
    data = {"names": sample[0], "date": sample[1], "time": sample[2], "venue": sample[3],
            "text": DEFAULT_TEXT[demo_lang], "lang": demo_lang}
    workdir = tempfile.mkdtemp(prefix="demo_")
    try:
        _, poster, _ = await asyncio.to_thread(studio.make_invitation, data, workdir, random.randint(1, 10**6), None, False)
        with open(poster, "rb") as fh:
            raw = fh.read()
        await bot.send_photo(callback.message.chat.id, BufferedInputFile(raw, filename="namuna.png"),
                             caption=T(uid, "demo_caption"))
    except Exception:
        logging.exception("demo xatosi")
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


# ============================================================================================
# TAKLIFNOMA YASASH
# ============================================================================================
BUSY = set()
QUEUE = {"n": 0}
RENDER_SEM = None
LAST_ORDER = {}
_LAT = re.compile(r"[A-Za-z]")
_CYR = re.compile(r"[А-Яа-яЁёЎўҚқҒғҲҳ]")


def clean(s, n):
    return re.sub(r"\s+", " ", (s or "").strip())[:n]


async def begin_invite(message, state):
    uid = message.from_user.id
    if not has_access(uid):
        return await message.answer(T(uid, "pay_need") + pay_info_text(uid), reply_markup=pay_kb(uid))
    if uid in BUSY:
        return await message.answer(T(uid, "inv_busy"))
    await state.set_state(Inv.names)
    await state.update_data(order={})
    await message.answer(T(uid, "inv_names"))


async def _store(state, **kw):
    data = await state.get_data()
    order = dict(data.get("order") or {})
    order.update(kw)
    await state.update_data(order=order)
    return order


def _reject_command(message):
    return (message.text or "").startswith("/")


@dp.message(Inv.names, F.text)
async def inv_names(message: types.Message, state: FSMContext):
    uid = message.from_user.id
    if _reject_command(message):
        return
    v = clean(message.text, 80)
    if len(v) < 3:
        return await message.answer(T(uid, "inv_names"))
    await _store(state, names=v)
    await state.set_state(Inv.date)
    await message.answer(T(uid, "inv_date"))


@dp.message(Inv.date, F.text)
async def inv_date(message: types.Message, state: FSMContext):
    uid = message.from_user.id
    if _reject_command(message):
        return
    v = clean(message.text, 40)
    if len(v) < 3:
        return await message.answer(T(uid, "inv_date"))
    await _store(state, date=v)
    await state.set_state(Inv.time)
    await message.answer(T(uid, "inv_time"))


@dp.message(Inv.time, F.text)
async def inv_time(message: types.Message, state: FSMContext):
    uid = message.from_user.id
    if _reject_command(message):
        return
    v = clean(message.text, 15)
    await _store(state, time="" if v in ("-", "—", "") else v)
    await state.set_state(Inv.venue)
    await message.answer(T(uid, "inv_venue"))


@dp.message(Inv.venue, F.text)
async def inv_venue(message: types.Message, state: FSMContext):
    uid = message.from_user.id
    if _reject_command(message):
        return
    v = clean(message.text, 140)
    if len(v) < 2:
        return await message.answer(T(uid, "inv_venue"))
    await _store(state, venue=v)
    await state.set_state(Inv.lang)
    await message.answer(T(uid, "inv_lang"), reply_markup=ikb([
        [btn(LANG_NAMES["uz"], "il:uz"), btn(LANG_NAMES["uz_cyrl"], "il:uz_cyrl")],
        [btn(LANG_NAMES["ru"], "il:ru"), btn(LANG_NAMES["en"], "il:en")]]))


@dp.callback_query(Inv.lang, F.data.startswith("il:"))
async def inv_lang(callback: types.CallbackQuery, state: FSMContext):
    uid = callback.from_user.id
    lang = callback.data.split(":")[1]
    if lang not in LANGS:
        return await callback.answer()
    await callback.answer()
    await _store(state, lang=lang)
    await state.set_state(Inv.text)
    await callback.message.answer(T(uid, "inv_text"), reply_markup=ikb([
        [btn(T(uid, "inv_text_ai"), "it:ai")], [btn(T(uid, "inv_text_own"), "it:own")]]))


async def ask_style(chat_id, uid, state):
    await state.set_state(Inv.style)
    await bot.send_message(chat_id, T(uid, "inv_style"), reply_markup=ikb([
        [btn(T(uid, "inv_style_rand"), "is:rand")],
        [btn(T(uid, "inv_style_pal"), "is:pal")],
        [btn(T(uid, "inv_style_desc"), "is:desc")]]))


@dp.callback_query(Inv.text, F.data.startswith("it:"))
async def inv_text_mode(callback: types.CallbackQuery, state: FSMContext):
    uid = callback.from_user.id
    mode = callback.data.split(":")[1]
    await callback.answer()
    order = (await state.get_data()).get("order") or {}
    if mode == "own":
        return await callback.message.answer(T(uid, "inv_text_prompt"))
    await bot.send_chat_action(callback.message.chat.id, "typing")
    lang = order.get("lang", "uz")
    try:
        text = await ai_invite_text(order.get("names", ""), lang)
        if len(text) < 10:
            raise AIError("qisqa")
    except Exception as ex:
        logging.info("AI matn yozolmadi: %s", ex)
        text = DEFAULT_TEXT[lang]
    await _store(state, text=text)
    await callback.message.answer(T(uid, "inv_ai_text_used", text=esc(text)))
    await ask_style(callback.message.chat.id, uid, state)


@dp.message(Inv.text, F.text)
async def inv_text_own(message: types.Message, state: FSMContext):
    uid = message.from_user.id
    if _reject_command(message):
        return
    v = clean(message.text, 220)
    if len(v) < 5:
        return await message.answer(T(uid, "inv_text_prompt"))
    await _store(state, text=v)
    await ask_style(message.chat.id, uid, state)


def palette_kb(uid):
    labels = PALETTE_LABELS[get_lang(uid) or "uz"]
    keys = list(studio.PALETTES)
    rows = []
    for i in range(0, len(keys), 2):
        rows.append([btn(labels[k], f"ip:{k}") for k in keys[i:i + 2]])
    return ikb(rows)


async def ask_music(chat_id, uid, state):
    await state.set_state(Inv.music)
    await bot.send_message(chat_id, T(uid, "inv_music"), reply_markup=ikb([
        [btn(T(uid, "inv_music_auto"), "im:auto")], [btn(T(uid, "inv_music_own"), "im:own")]]))


@dp.callback_query(Inv.style, F.data.startswith("is:"))
async def inv_style_mode(callback: types.CallbackQuery, state: FSMContext):
    uid = callback.from_user.id
    mode = callback.data.split(":")[1]
    await callback.answer()
    if mode == "rand":
        await _store(state, palette=None, style=None)
        return await ask_music(callback.message.chat.id, uid, state)
    if mode == "pal":
        await state.set_state(Inv.palette)
        return await callback.message.answer(T(uid, "inv_pal"), reply_markup=palette_kb(uid))
    await state.set_state(Inv.styletext)
    await callback.message.answer(T(uid, "inv_style_text"))


@dp.callback_query(Inv.palette, F.data.startswith("ip:"))
async def inv_palette(callback: types.CallbackQuery, state: FSMContext):
    uid = callback.from_user.id
    key = callback.data.split(":")[1]
    if key not in studio.PALETTES:
        return await callback.answer()
    await callback.answer()
    await _store(state, palette=key, style=None)
    await ask_music(callback.message.chat.id, uid, state)


@dp.message(Inv.styletext, F.text)
async def inv_style_text(message: types.Message, state: FSMContext):
    uid = message.from_user.id
    if _reject_command(message):
        return
    desc = clean(message.text, 300)
    await bot.send_chat_action(message.chat.id, "typing")
    palette, style = None, None
    try:
        palette, style = await ai_design(desc)
    except Exception as ex:
        logging.info("AI dizayn tanlolmadi, tasodifiy: %s", ex)
    await _store(state, palette=palette, style=style)
    await ask_music(message.chat.id, uid, state)


@dp.callback_query(Inv.music, F.data.startswith("im:"))
async def inv_music_mode(callback: types.CallbackQuery, state: FSMContext):
    uid = callback.from_user.id
    mode = callback.data.split(":")[1]
    await callback.answer()
    if mode == "own":
        await state.set_state(Inv.musicfile)
        return await callback.message.answer(T(uid, "inv_music_prompt"))
    order = await _store(state, music_fid=None)
    await state.clear()
    await start_generation(callback.message.chat.id, uid, order)


@dp.message(Inv.musicfile, F.audio | F.voice | F.document)
async def inv_music_file(message: types.Message, state: FSMContext):
    uid = message.from_user.id
    f = message.audio or message.voice or message.document
    if message.document and not ((message.document.mime_type or "").startswith("audio/")
                                 or (message.document.file_name or "").lower().endswith((".mp3", ".m4a", ".wav", ".ogg", ".aac"))):
        return await message.answer(T(uid, "inv_music_bad"))
    if (f.file_size or 0) > 19 * 1024 * 1024:
        return await message.answer(T(uid, "inv_music_bad"))
    order = await _store(state, music_fid=f.file_id)
    await state.clear()
    await start_generation(message.chat.id, uid, order)


@dp.message(Inv.musicfile)
async def inv_music_other(message: types.Message):
    await message.answer(T(message.from_user.id, "inv_music_bad"))


def make_studio_data(order):
    """Foydalanuvchi kiritgan ma'lumotni taklifnoma tiliga moslaydi (lotin ↔ kirill)."""
    lang = order.get("lang", "uz")
    fields = {k: order.get(k, "") for k in ("names", "date", "time", "venue", "text")}
    for k, v in fields.items():
        if lang == "uz_cyrl" and _LAT.search(v):
            fields[k] = to_cyrillic(v)
        elif lang == "uz" and _CYR.search(v):
            fields[k] = to_latin(v)
    return {**fields, "lang": lang, "palette": order.get("palette"), "style": order.get("style")}


async def pick_music_file(workdir, order, music_seed):
    """Foydalanuvchi musiqasi → admin kutubxonasi (tasodifiy) → None (sintez qilinadi)."""
    fid = order.get("music_fid")
    if not fid:
        with db() as c:
            rows = c.execute("SELECT file_id FROM music").fetchall()
        if not rows:
            return None
        fid = random.Random(music_seed).choice(rows)[0]
    path = os.path.join(workdir, "music_src")
    try:
        await bot.download(fid, destination=path)
        if os.path.getsize(path) > 1000:
            return path
    except Exception as ex:
        logging.info("musiqa yuklab bo'lmadi: %s", ex)
    return None


async def start_generation(chat_id, uid, order, new_design=False, new_music=False):
    order = dict(order)
    order.setdefault("seed", random.randint(1, 10 ** 9))
    order.setdefault("music_seed", order["seed"])
    if new_design:
        order["seed"] = random.randint(1, 10 ** 9)
        order["palette"], order["style"] = None, None
    if new_music:
        order["music_seed"] = random.randint(1, 10 ** 9)
    LAST_ORDER[uid] = order
    if uid in BUSY:
        return await bot.send_message(chat_id, T(uid, "inv_busy"))
    BUSY.add(uid)
    status = None
    workdir = None
    try:
        ahead = QUEUE["n"]
        status = await bot.send_message(chat_id, T(uid, "inv_working") if ahead == 0 else T(uid, "inv_queue", n=ahead))
        QUEUE["n"] += 1
        try:
            async with RENDER_SEM:
                workdir = tempfile.mkdtemp(prefix="tk_")
                sdata = make_studio_data(order)
                music = await pick_music_file(workdir, order, order["music_seed"])
                novideo = False
                try:
                    video, poster, _info = await asyncio.to_thread(
                        studio.make_invitation, sdata, workdir, order["seed"], music, True, order["music_seed"])
                except Exception:
                    logging.exception("video yasashda xato")
                    video, novideo = None, True
                    _v, poster, _info = await asyncio.to_thread(
                        studio.make_invitation, sdata, workdir, order["seed"], None, False)
        finally:
            QUEUE["n"] -= 1
        kb = ikb([[btn(T(uid, "inv_again_design"), "ir:design"), btn(T(uid, "inv_again_music"), "ir:music")],
                  [btn(T(uid, "inv_new"), "ir:new")]])
        caption = T(uid, "inv_done", names=esc(sdata["names"]))
        if novideo:
            caption += "\n" + T(uid, "inv_novideo")
        if video:
            await bot.send_video(chat_id, FSInputFile(video, filename="taklifnoma.mp4"), caption=caption,
                                 reply_markup=kb, supports_streaming=True, width=studio.W, height=studio.H,
                                 duration=int(studio.DURATION))
            with open(poster, "rb") as fh:
                await bot.send_photo(chat_id, BufferedInputFile(fh.read(), filename="taklifnoma.png"))
        else:
            with open(poster, "rb") as fh:
                await bot.send_photo(chat_id, BufferedInputFile(fh.read(), filename="taklifnoma.png"),
                                     caption=caption, reply_markup=kb)
        with db() as c:
            c.execute("INSERT INTO orders (user_id, created, lang) VALUES (?, ?, ?)", (uid, int(time.time()), order.get("lang")))
            c.commit()
    except Exception:
        logging.exception("taklifnoma yuborishda xato")
        try:
            await bot.send_message(chat_id, T(uid, "err"))
        except Exception:
            pass
    finally:
        BUSY.discard(uid)
        if workdir:
            shutil.rmtree(workdir, ignore_errors=True)
        if status:
            try:
                await status.delete()
            except Exception:
                pass


@dp.callback_query(F.data.in_({"ir:design", "ir:music"}))
async def inv_again(callback: types.CallbackQuery, state: FSMContext):
    uid = callback.from_user.id
    await callback.answer()
    act = callback.data.split(":")[1]
    if not has_access(uid):
        return await callback.message.answer(T(uid, "pay_need") + pay_info_text(uid), reply_markup=pay_kb(uid))
    order = LAST_ORDER.get(uid)
    if not order:
        return await callback.message.answer(T(uid, "inv_expired"))
    await start_generation(callback.message.chat.id, uid, order, new_design=(act == "design"), new_music=(act == "music"))


# «Yangi taklifnoma» tugmasi (callback'da message.from_user bot bo'lgani uchun alohida handler)
@dp.callback_query(F.data == "ir:new")
async def inv_new_cb(callback: types.CallbackQuery, state: FSMContext):
    uid = callback.from_user.id
    await callback.answer()
    await state.clear()
    if not has_access(uid):
        return await callback.message.answer(T(uid, "pay_need") + pay_info_text(uid), reply_markup=pay_kb(uid))
    if uid in BUSY:
        return await callback.message.answer(T(uid, "inv_busy"))
    await state.set_state(Inv.names)
    await state.update_data(order={})
    await callback.message.answer(T(uid, "inv_names"))


# ============================================================================================
# TARJIMA va XATOLARNI TOPISH
# ============================================================================================
def tr_lang_kb():
    keys = list(TR_LANGS)
    rows = []
    for i in range(0, len(keys), 2):
        rows.append([btn(TR_LANGS[k][0], f"tt:{k}") for k in keys[i:i + 2]])
    return ikb(rows)


@dp.callback_query(F.data.startswith("tt:"))
async def cb_tr_lang(callback: types.CallbackQuery, state: FSMContext):
    uid = callback.from_user.id
    code = callback.data.split(":")[1]
    await callback.answer()
    if code == "menu":
        return await callback.message.answer(T(uid, "tr_pick"), reply_markup=tr_lang_kb())
    if code not in TR_LANGS:
        return
    await state.set_state(Tr.wait)
    await state.update_data(target=code)
    await callback.message.answer(T(uid, "tr_ready", lang=esc(TR_LANGS[code][0])),
                                  reply_markup=ikb([[btn(T(uid, "tr_change"), "tt:menu")]]))


async def ai_gate(message, uid):
    """Bepul limit / kalit tekshiruvi. True — davom etish mumkin."""
    if not quota_ok(uid):
        await message.answer(T(uid, "free_over", n=FREE_DAILY), reply_markup=pay_kb(uid))
        return False
    return True


@dp.message(Tr.wait, F.text, ~F.text.startswith("/"))
async def tr_text(message: types.Message, state: FSMContext):
    uid = message.from_user.id
    text = (message.text or "").strip()
    if len(text) > 3500:
        return await message.answer(T(uid, "ai_too_long"))
    if not await ai_gate(message, uid):
        return
    target = (await state.get_data()).get("target", "en")
    status = await message.answer(T(uid, "ai_working"))
    try:
        out = await ai_translate(text, target)
    except Exception as ex:
        logging.warning("tarjima xatosi: %s", ex)
        return await status.edit_text(T(uid, "ai_fail"))
    quota_use(uid)
    try:
        await status.delete()
    except Exception:
        pass
    await send_long(message.chat.id, T(uid, "tr_result", lang=esc(TR_LANGS[target][0]), text=esc(out)),
                    reply_markup=ikb([[btn(T(uid, "tr_change"), "tt:menu")]]))


@dp.message(Tr.wait, F.photo | F.document)
async def tr_photo(message: types.Message, state: FSMContext):
    uid = message.from_user.id
    if not await ai_gate(message, uid):
        return
    target = (await state.get_data()).get("target", "en")
    status = await message.answer(T(uid, "ai_working"))
    try:
        b64 = await get_image_b64(message)
        if not b64:
            return await status.edit_text(T(uid, "ai_no_text"))
        res = await ai_vision_translate(b64, target)
    except Exception as ex:
        logging.warning("rasm tarjimasi xatosi: %s", ex)
        return await status.edit_text(T(uid, "ai_fail"))
    try:
        await status.delete()
    except Exception:
        pass
    if not res["translation"] and not res["original"]:
        return await message.answer(T(uid, "ai_no_text_found"))
    quota_use(uid)
    parts = []
    if res["original"]:
        parts.append(T(uid, "tr_original", text=esc(res["original"])))
    parts.append(T(uid, "tr_result", lang=esc(TR_LANGS[target][0]), text=esc(res["translation"])))
    await send_long(message.chat.id, "\n\n".join(parts), reply_markup=ikb([[btn(T(uid, "tr_change"), "tt:menu")]]))


def format_errors(uid, errors):
    items = []
    for e in errors[:15]:
        line = f"• <s>{esc(e.get('wrong'))}</s> → <b>{esc(e.get('right'))}</b>"
        if e.get("reason"):
            line += f"\n   <i>{esc(e.get('reason'))}</i>"
        items.append(line)
    return T(uid, "gr_errors", items="\n".join(items))


async def send_grammar_result(chat_id, uid, res):
    original = res.get("original") or ""
    corrected = res.get("corrected") or ""
    parts = []
    if original:
        parts.append(T(uid, "tr_original", text=esc(original)))
    if res["errors"] or (corrected and corrected.strip() != original.strip() and original):
        parts.append(T(uid, "gr_fixed", text=esc(corrected)))
        if res["errors"]:
            parts.append(format_errors(uid, res["errors"]))
    else:
        parts.append(T(uid, "gr_none"))
    await send_long(chat_id, "\n\n".join(parts))


@dp.message(Gr.wait, F.text, ~F.text.startswith("/"))
async def gr_text(message: types.Message):
    uid = message.from_user.id
    text = (message.text or "").strip()
    if len(text) > 3500:
        return await message.answer(T(uid, "ai_too_long"))
    if not await ai_gate(message, uid):
        return
    status = await message.answer(T(uid, "ai_working"))
    try:
        res = await ai_grammar(text, get_lang(uid) or "uz")
    except Exception as ex:
        logging.warning("grammatika xatosi: %s", ex)
        return await status.edit_text(T(uid, "ai_fail"))
    quota_use(uid)
    try:
        await status.delete()
    except Exception:
        pass
    same = res["corrected"].strip() == text and not res["errors"]
    if same:
        return await message.answer(T(uid, "gr_none"))
    await send_grammar_result(message.chat.id, uid, {**res, "original": ""})


@dp.message(Gr.wait, F.photo | F.document)
async def gr_photo(message: types.Message):
    uid = message.from_user.id
    if not await ai_gate(message, uid):
        return
    status = await message.answer(T(uid, "ai_working"))
    try:
        b64 = await get_image_b64(message)
        if not b64:
            return await status.edit_text(T(uid, "ai_no_text"))
        res = await ai_vision_grammar(b64, get_lang(uid) or "uz")
    except Exception as ex:
        logging.warning("rasm grammatikasi xatosi: %s", ex)
        return await status.edit_text(T(uid, "ai_fail"))
    try:
        await status.delete()
    except Exception:
        pass
    if not res["original"] and not res["corrected"]:
        return await message.answer(T(uid, "ai_no_text_found"))
    quota_use(uid)
    await send_grammar_result(message.chat.id, uid, res)


# ============================================================================================
# ADMIN
# ============================================================================================
def admin_kb():
    return ikb([[btn("📊 Statistika", "ad:stats"), btn("💳 Kutilayotgan to'lovlar", "ad:pending")],
                [btn("🎵 Musiqa kutubxonasi", "ad:music")],
                [btn("💾 Backup", "ad:backup")]])


@dp.message(Command("admin"))
async def cmd_admin(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return await message.answer(f"⛔ Faqat admin uchun. Sizning ID: <code>{message.from_user.id}</code>")
    await state.clear()
    await message.answer("🛠 <b>Admin panel</b>\n\nBuyruqlar:\n"
                         "<code>/grant ID [kun]</code> — obuna berish (kun yozilmasa standart muddat)\n"
                         "<code>/revoke ID</code> — obunani olib tashlash\n"
                         "<code>/aitest</code> — Groq ulanishini tekshirish\n"
                         "<code>/myid</code> — ID ni bilish", reply_markup=admin_kb())


@dp.message(Command("myid"))
async def cmd_myid(message: types.Message):
    await message.answer(f"🆔 <code>{message.from_user.id}</code>")


@dp.message(Command("grant"))
async def cmd_grant(message: types.Message, command: CommandObject):
    if not is_admin(message.from_user.id):
        return
    parts = (command.args or "").split()
    if not parts or not parts[0].isdigit():
        return await message.answer("Foydalanish: <code>/grant 123456789 [kun]</code>")
    uid = int(parts[0])
    days = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None
    grant_access(uid, days)
    await message.answer(f"✅ {uid} ga obuna berildi: {until_text(uid)}")
    try:
        await bot.send_message(uid, T(uid, "pay_ok"))
    except Exception:
        pass
    run_bg(safe_push_backup())


@dp.message(Command("revoke"))
async def cmd_revoke(message: types.Message, command: CommandObject):
    if not is_admin(message.from_user.id):
        return
    arg = (command.args or "").strip()
    if not arg.isdigit():
        return await message.answer("Foydalanish: <code>/revoke 123456789</code>")
    revoke_access(int(arg))
    await message.answer(f"✅ {arg} obunasi olib tashlandi.")
    run_bg(safe_push_backup())


@dp.message(Command("aitest"))
async def cmd_aitest(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    if not GROQ_KEY:
        return await message.answer("❌ GROQ_API_KEY topilmadi. Render → Environment ga <code>GROQ_API_KEY</code> kiriting.")
    await message.answer(f"🔑 Kalit: <code>{GROQ_KEY[:6]}…{GROQ_KEY[-4:]}</code>\n⏳ Sinayapman...")
    t0 = time.monotonic()
    try:
        out = await groq_chat([{"role": "user", "content": "Reply with one word: OK"}], max_tokens=200, temperature=0, deadline=30)
        await message.answer(f"✅ AI ishlayapti ({time.monotonic() - t0:.1f} s). Javob: <code>{esc(out[:60])}</code>\n"
                             f"Matn modellari: {esc(', '.join(TEXT_MODELS))}\nRasm modellari: {esc(', '.join(VISION_MODELS))}")
    except Exception as ex:
        await message.answer(f"❌ AI xatosi:\n<code>{esc(str(ex)[:500])}</code>")


@dp.callback_query(F.data == "ad:stats")
async def ad_stats(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        return await callback.answer("⛔", show_alert=True)
    await callback.answer()
    now = int(time.time())
    with db() as c:
        users = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        paid = c.execute("SELECT COUNT(*) FROM users WHERE paid_until > ?", (now,)).fetchone()[0]
        pend = c.execute("SELECT COUNT(*) FROM payments WHERE status = 'pending'").fetchone()[0]
        appr = c.execute("SELECT COUNT(*), COALESCE(SUM(amount), 0) FROM payments WHERE status = 'approved'").fetchone()
        orders = c.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
        music = c.execute("SELECT COUNT(*) FROM music").fetchone()[0]
    await callback.message.answer(
        f"📊 <b>Statistika</b>\n\n👥 Foydalanuvchilar: {users}\n✅ Obunali: {paid}\n⏳ Kutilayotgan to'lovlar: {pend}\n"
        f"💰 Tasdiqlangan to'lovlar: {appr[0]} ta ({money(appr[1])} so'm)\n🎬 Yasalgan taklifnomalar: {orders}\n🎵 Musiqa: {music} ta")


@dp.callback_query(F.data == "ad:pending")
async def ad_pending(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        return await callback.answer("⛔", show_alert=True)
    await callback.answer()
    with db() as c:
        rows = c.execute("SELECT p.id, p.user_id, p.file_id, p.ftype, u.name, u.username FROM payments p "
                         "LEFT JOIN users u ON u.user_id = p.user_id WHERE p.status = 'pending' ORDER BY p.id").fetchall()
    if not rows:
        return await callback.message.answer("Kutilayotgan to'lov yo'q.")
    for pid, uid, fid, ftype, name, uname in rows:
        caption = (f"💳 <b>To'lov #{pid}</b>\n👤 {esc(name or '')}" + (f" (@{esc(uname)})" if uname else "")
                   + f"\n🆔 <code>{uid}</code>")
        kb = ikb([[btn("✅ Tasdiqlash", f"pay:ok:{pid}"), btn("❌ Rad etish", f"pay:no:{pid}")]])
        try:
            if ftype == "photo":
                await bot.send_photo(callback.message.chat.id, fid, caption=caption, reply_markup=kb)
            else:
                await bot.send_document(callback.message.chat.id, fid, caption=caption, reply_markup=kb)
        except Exception as ex:
            logging.warning("kutilayotgan chek yuborilmadi: %s", ex)


# ---- musiqa kutubxonasi
@dp.callback_query(F.data == "ad:music")
async def ad_music(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return await callback.answer("⛔", show_alert=True)
    await callback.answer()
    await state.clear()
    with db() as c:
        rows = c.execute("SELECT id, title FROM music ORDER BY id").fetchall()
    kb = [[btn(f"🗑 {(t or 'musiqa')[:34]}", f"ad:mdel:{i}")] for i, t in rows[:30]]
    kb.append([btn("➕ Musiqa qo'shish", "ad:madd")])
    await callback.message.answer(
        f"🎵 <b>Musiqa kutubxonasi</b>: {len(rows)} ta\n\nBu yerga qo'shilgan musiqalardan bot taklifnomalarga tasodifiy tanlaydi. "
        "Kutubxona bo'sh bo'lsa, bot musiqani o'zi sintez qiladi.\n⚠️ Faqat ruxsatli (mualliflik huquqi bilan bog'liq muammosiz) musiqa qo'shing.",
        reply_markup=ikb(kb))


@dp.callback_query(F.data == "ad:madd")
async def ad_music_add(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return await callback.answer("⛔", show_alert=True)
    await callback.answer()
    await state.set_state(AdmMusic.add)
    await callback.message.answer("🎧 Audio (mp3) fayllarni ketma-ket yuboring. Tugagach /done yozing.")


@dp.message(AdmMusic.add, Command("done"))
async def ad_music_done(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("✅ Tayyor.", reply_markup=menu_kb(get_lang(message.from_user.id) or "uz"))
    run_bg(safe_push_backup())


@dp.message(AdmMusic.add, F.audio | F.voice | F.document)
async def ad_music_file(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    f = message.audio or message.voice or message.document
    title = (getattr(f, "title", None) or getattr(f, "file_name", None) or "musiqa")[:60]
    with db() as c:
        c.execute("INSERT INTO music (file_id, title, added) VALUES (?, ?, ?)", (f.file_id, title, int(time.time())))
        n = c.execute("SELECT COUNT(*) FROM music").fetchone()[0]
        c.commit()
    await message.answer(f"✅ Qo'shildi: {esc(title)} (jami {n} ta). Yana yuboring yoki /done")


@dp.callback_query(F.data.startswith("ad:mdel:"))
async def ad_music_del(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        return await callback.answer("⛔", show_alert=True)
    mid = int(callback.data.split(":")[2])
    with db() as c:
        c.execute("DELETE FROM music WHERE id = ?", (mid,))
        c.commit()
    await callback.answer("🗑 O'chirildi")
    try:
        await callback.message.delete()
    except Exception:
        pass
    run_bg(safe_push_backup())


# ============================================================================================
# Zaxira nusxa (Render qayta ishga tushganda baza yo'qolmasligi uchun)
# ============================================================================================
BACKUP_NAME = "taklifnoma_backup.db"
_backup_state = {"hash": None}
_restore_ran = [False]
RESTORE_DONE = None
_backup_lock = None
restore_wait = set()


def _admin_chat_id():
    return sorted(ADMIN_IDS)[0] if ADMIN_IDS else None


def make_backup_file():
    fd, path = tempfile.mkstemp(prefix="tk_backup_", suffix=".db")
    os.close(fd)
    with db() as src, closing(sqlite3.connect(path)) as dst:
        src.backup(dst)
    return path


def restore_db_file(path):
    try:
        with closing(sqlite3.connect(path)) as c:
            names = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if c.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                return False
    except sqlite3.Error:
        return False
    if not {"users", "payments"} <= names:
        return False
    shutil.copyfile(path, DB_PATH + ".new")
    os.replace(DB_PATH + ".new", DB_PATH)
    init_db()
    _LANG.clear()
    return True


def db_fingerprint():
    h = hashlib.sha1()
    with db() as c:
        for q in ("SELECT user_id, lang, paid_until FROM users ORDER BY user_id",
                  "SELECT id, status, user_id FROM payments ORDER BY id",
                  "SELECT id, file_id FROM music ORDER BY id"):
            for row in c.execute(q):
                h.update(repr(row).encode("utf-8", "ignore"))
    return h.hexdigest()


def db_has_data():
    with db() as c:
        return bool(c.execute("SELECT (SELECT COUNT(*) FROM users) + (SELECT COUNT(*) FROM payments)").fetchone()[0])


async def _pinned_backup(chat_id):
    try:
        chat = await bot.get_chat(chat_id)
        pm = getattr(chat, "pinned_message", None)
        me = await bot.me()
        doc = getattr(pm, "document", None) if pm else None
        sender = getattr(pm, "from_user", None) if pm else None
        if doc and (doc.file_name or "") == BACKUP_NAME and getattr(sender, "id", None) == me.id:
            return pm
    except Exception as ex:
        logging.info("qadalgan zaxira topilmadi: %s", ex)
    return None


async def push_backup(chat_id, force=False):
    async with _backup_lock:
        fp = await asyncio.to_thread(db_fingerprint)
        if not force and fp == _backup_state["hash"]:
            return False
        path = await asyncio.to_thread(make_backup_file)
        try:
            caption = "💾 Avtomatik zaxira (yangilanib turadi) · " + time.strftime("%d.%m %H:%M", time.gmtime()) + " UTC"
            pm = await _pinned_backup(chat_id)
            done = False
            if pm:
                try:
                    await bot.edit_message_media(
                        chat_id=chat_id, message_id=pm.message_id,
                        media=InputMediaDocument(media=FSInputFile(path, filename=BACKUP_NAME), caption=caption))
                    done = True
                except Exception as ex:
                    logging.info("zaxirani joyida yangilab bo'lmadi: %s", ex)
            if not done:
                m = await bot.send_document(chat_id, FSInputFile(path, filename=BACKUP_NAME), caption=caption,
                                            disable_notification=True)
                try:
                    await bot.pin_chat_message(chat_id, m.message_id, disable_notification=True)
                except Exception as ex:
                    logging.warning("zaxirani qadab bo'lmadi: %s", ex)
            _backup_state["hash"] = fp
            return True
        finally:
            try:
                os.remove(path)
            except OSError:
                pass


async def safe_push_backup(force=False):
    if RESTORE_DONE is None or not RESTORE_DONE.is_set():
        return
    chat_id = _admin_chat_id()
    if not chat_id:
        return
    try:
        await push_backup(chat_id, force=force)
    except Exception as ex:
        logging.warning("zaxira xatosi: %s", ex)


async def startup_restore():
    try:
        chat_id = _admin_chat_id()
        if not chat_id:
            logging.info("ADMIN_ID yo'q: avtomatik tiklash o'chiq")
            return
        if await asyncio.to_thread(db_has_data):
            _backup_state["hash"] = await asyncio.to_thread(db_fingerprint)
            return
        pm = await _pinned_backup(chat_id)
        if not pm:
            logging.info("qadalgan zaxira yo'q: bo'sh baza bilan boshlanadi")
            return
        fd, tmp = tempfile.mkstemp(prefix="auto_restore_", suffix=".db")
        os.close(fd)
        try:
            await bot.download(pm.document.file_id, destination=tmp)
            ok = await asyncio.to_thread(restore_db_file, tmp)
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass
        if ok:
            _backup_state["hash"] = await asyncio.to_thread(db_fingerprint)
            logging.info("Baza avtomatik tiklandi")
            try:
                await bot.send_message(chat_id, "✅ Baza avtomatik tiklandi (qadalgan zaxiradan).")
            except Exception:
                pass
    except Exception:
        logging.exception("avtomatik tiklash xatosi")
    finally:
        RESTORE_DONE.set()


async def startup_restore_once():
    if _restore_ran[0]:
        return
    _restore_ran[0] = True
    await startup_restore()


async def backup_worker():
    await RESTORE_DONE.wait()
    await asyncio.sleep(30)
    while True:
        try:
            chat_id = _admin_chat_id()
            if chat_id:
                await push_backup(chat_id)
        except Exception as ex:
            logging.warning("auto-backup xatosi: %s", ex)
        await asyncio.sleep(max(BACKUP_MINUTES, 1) * 60)


async def send_backup(chat_id, caption):
    path = await asyncio.to_thread(make_backup_file)
    try:
        await bot.send_document(chat_id, FSInputFile(path, filename=f"taklifnoma_{datetime.now():%Y%m%d_%H%M}.db"), caption=caption)
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


@dp.callback_query(F.data == "ad:backup")
async def ad_backup(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        return await callback.answer("⛔", show_alert=True)
    await callback.answer()
    await send_backup(callback.message.chat.id, "💾 Baza nusxasi. Tiklash: /restore")


@dp.message(Command("backup"))
async def cmd_backup(message: types.Message):
    if is_admin(message.from_user.id):
        await send_backup(message.chat.id, "💾 Baza nusxasi. Tiklash: /restore")


@dp.message(Command("restore"))
async def cmd_restore(message: types.Message, state: FSMContext):
    if is_admin(message.from_user.id):
        await state.clear()
        restore_wait.add(message.from_user.id)
        await message.answer("📥 Endi avval olingan .db faylni yuboring. ⚠️ Hozirgi baza almashtiriladi!\nBekor qilish: /cancel")


@dp.message(StateFilter(None), F.document)
async def on_restore_document(message: types.Message):
    uid = message.from_user.id
    if uid not in restore_wait or not is_admin(uid):
        return
    restore_wait.discard(uid)
    fd, tmp = tempfile.mkstemp(prefix=f"restore_{uid}_", suffix=".db")
    os.close(fd)
    try:
        await bot.download(message.document.file_id, destination=tmp)
        ok = await asyncio.to_thread(restore_db_file, tmp)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    await message.answer("✅ Baza tiklandi!" if ok else "❌ Bu fayl mos emas yoki buzilgan.")
    if ok:
        run_bg(safe_push_backup(force=True))


# ============================================================================================
# Qolgan xabarlar va xatolar
# ============================================================================================
@dp.message(StateFilter(None))
async def fallback(message: types.Message):
    uid = message.from_user.id
    upsert_user(message.from_user)
    if not get_lang(uid):
        return await message.answer(LANG_PICK_TEXT, reply_markup=lang_kb())
    await message.answer(T(uid, "welcome", name=esc(message.from_user.first_name or "")), reply_markup=menu_kb(get_lang(uid)))


@dp.errors()
async def on_error(event: ErrorEvent):
    logging.exception("Handler xatosi: %s", event.exception)
    try:
        upd = event.update
        chat_id = None
        uid = None
        if upd.message:
            chat_id, uid = upd.message.chat.id, upd.message.from_user.id
        elif upd.callback_query and upd.callback_query.message:
            chat_id, uid = upd.callback_query.message.chat.id, upd.callback_query.from_user.id
        if chat_id:
            await bot.send_message(chat_id, T(uid, "err"))
    except Exception:
        pass
    return True


async def main():
    global RESTORE_DONE, _backup_lock, RENDER_SEM, _ai_sem
    RESTORE_DONE = asyncio.Event()
    _backup_lock = asyncio.Lock()
    RENDER_SEM = asyncio.Semaphore(1)       # bir vaqtda faqat bitta video (xotira va CPU tejash)
    _ai_sem = asyncio.Semaphore(6)
    threading.Thread(target=self_ping, daemon=True).start()
    await start_web_server()
    run_bg(backup_worker())
    while True:
        try:
            await wait_for_valid_token()
            await startup_restore_once()
            logging.info("Bot polling boshlandi...")
            await bot.delete_webhook(drop_pending_updates=True)
            await dp.start_polling(bot, drop_pending_updates=True)
            logging.info("Polling to'xtatildi, bot o'chmoqda.")
            break
        except Exception as ex:
            logging.error("Polling xatoligi: %s", ex)
            await asyncio.sleep(5)
    try:
        if _admin_chat_id():
            await asyncio.wait_for(push_backup(_admin_chat_id()), timeout=8)
    except Exception:
        pass
    if _http and not _http.closed:
        await _http.close()
    await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
