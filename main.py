import os, sys, asyncio, logging
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
from dotenv import load_dotenv
import aiosqlite

from aiogram import Bot, Dispatcher, F, Router
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery, BotCommand,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton
)

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

BOT_TOKEN = os.getenv("BOT_TOKEN", "8871611449:AAEqnJxlmrBEWYKACn7L4j-FaociSm4TyNE").strip()
_admins_str = os.getenv("ADMINS", "8668733221").strip()
ADMIN_IDS = {int(x.strip()) for x in _admins_str.split(",") if x.strip().isdigit()}

_channels_str = os.getenv("CHANNELS", "@islomovasadbek").strip()
CONFIG_CHANNELS = [x.strip() for x in _channels_str.split(",") if x.strip()]

DB_PATH = BASE_DIR / os.getenv("DB_PATH", "data/kino_bot.db")
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("IslomovKinoBot")

def is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS

def parse_cid(cid: str):
    c = str(cid).strip()
    return int(c) if (c.startswith("-") and c[1:].isdigit()) or c.isdigit() else c

class Database:
    def __init__(self, path=DB_PATH):
        self.path = path

    async def init_db(self):
        async with aiosqlite.connect(self.path) as db:
            await db.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, username TEXT, full_name TEXT, joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
            await db.execute("CREATE TABLE IF NOT EXISTS movies (id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT UNIQUE NOT NULL, title TEXT NOT NULL, description TEXT, file_id TEXT NOT NULL, file_type TEXT DEFAULT 'video', views INTEGER DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
            await db.execute("CREATE TABLE IF NOT EXISTS channels (id INTEGER PRIMARY KEY AUTOINCREMENT, channel_id TEXT UNIQUE NOT NULL, title TEXT NOT NULL, invite_link TEXT NOT NULL)")
            await db.commit()

    async def add_user(self, uid: int, uname: Optional[str], fname: Optional[str]):
        async with aiosqlite.connect(self.path) as db:
            await db.execute("INSERT INTO users (user_id, username, full_name) VALUES (?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET username=excluded.username, full_name=excluded.full_name", (uid, uname, fname))
            await db.commit()

    async def get_user_count(self) -> int:
        async with aiosqlite.connect(self.path) as db:
            async with db.execute("SELECT COUNT(*) FROM users") as cur:
                r = await cur.fetchone()
                return r[0] if r else 0

    async def get_all_users(self) -> List[int]:
        async with aiosqlite.connect(self.path) as db:
            async with db.execute("SELECT user_id FROM users") as cur:
                return [r[0] for r in await cur.fetchall()]

    async def add_movie(self, code: str, title: str, fid: str, ftype: str = "video", desc: str = None) -> bool:
        try:
            async with aiosqlite.connect(self.path) as db:
                await db.execute("INSERT INTO movies (code, title, description, file_id, file_type) VALUES (?, ?, ?, ?, ?)", (code.strip(), title.strip(), desc, fid, ftype))
                await db.commit()
                return True
        except Exception:
            return False

    async def get_movie(self, code: str) -> Optional[Dict[str, Any]]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM movies WHERE code = ?", (code.strip(),)) as cur:
                r = await cur.fetchone()
                return dict(r) if r else None

    async def inc_views(self, code: str):
        async with aiosqlite.connect(self.path) as db:
            await db.execute("UPDATE movies SET views = views + 1 WHERE code = ?", (code.strip(),))
            await db.commit()

    async def del_movie(self, code: str) -> bool:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute("DELETE FROM movies WHERE code = ?", (code.strip(),))
            await db.commit()
            return cur.rowcount > 0

    async def search_movies(self, q: str, limit: int = 10) -> List[Dict[str, Any]]:
        p = f"%{q.strip()}%"
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT code, title, views FROM movies WHERE title LIKE ? OR description LIKE ? ORDER BY views DESC LIMIT ?", (p, p, limit)) as cur:
                return [dict(r) for r in await cur.fetchall()]

    async def get_random(self) -> Optional[Dict[str, Any]]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM movies ORDER BY RANDOM() LIMIT 1") as cur:
                r = await cur.fetchone()
                return dict(r) if r else None

    async def get_top(self, limit: int = 10) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT code, title, views FROM movies ORDER BY views DESC LIMIT ?", (limit,)) as cur:
                return [dict(r) for r in await cur.fetchall()]

    async def get_stats(self) -> Tuple[int, int, int]:
        async with aiosqlite.connect(self.path) as db:
            async with db.execute("SELECT COUNT(*) FROM users") as c1:
                u = (await c1.fetchone())[0]
            async with db.execute("SELECT COUNT(*), COALESCE(SUM(views), 0) FROM movies") as c2:
                r2 = await c2.fetchone()
                return u, r2[0], r2[1]

    async def next_code(self) -> str:
        async with aiosqlite.connect(self.path) as db:
            async with db.execute("SELECT MAX(CAST(code AS INTEGER)) FROM movies WHERE code GLOB '[0-9]*'") as cur:
                r = await cur.fetchone()
                return str(r[0] + 1) if r and r[0] is not None else "1"

    async def add_channel(self, cid: str, title: str, link: str):
        try:
            async with aiosqlite.connect(self.path) as db:
                await db.execute("INSERT INTO channels (channel_id, title, invite_link) VALUES (?, ?, ?) ON CONFLICT(channel_id) DO UPDATE SET title=excluded.title, invite_link=excluded.invite_link", (str(cid).strip(), title.strip(), link.strip()))
                await db.commit()
        except Exception as e:
            logger.warning(f"add_channel error: {e}")

    async def del_channel(self, cid: str):
        async with aiosqlite.connect(self.path) as db:
            await db.execute("DELETE FROM channels WHERE channel_id = ?", (str(cid).strip(),))
            await db.commit()

    async def get_channels(self) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM channels") as cur:
                return [dict(r) for r in await cur.fetchall()]

db = Database()

async def check_subs(bot: Bot, uid: int) -> Tuple[bool, List[Dict[str, Any]]]:
    channels = await db.get_channels()
    if not channels:
        return True, []
    unsub = []
    for ch in channels:
        try:
            m = await bot.get_chat_member(chat_id=parse_cid(ch["channel_id"]), user_id=uid)
            if m.status in [ChatMemberStatus.LEFT, ChatMemberStatus.KICKED]:
                unsub.append(ch)
        except TelegramBadRequest as e:
            err = str(e).lower()
            if any(k in err for k in ["user not found", "user_not_participant", "participant_id_invalid"]):
                unsub.append(ch)
        except Exception:
            pass
    return len(unsub) == 0, unsub

def main_kb(uid: int) -> ReplyKeyboardMarkup:
    k = [
        [KeyboardButton(text="🔍 Kino qidirish"), KeyboardButton(text="🎲 Tasodifiy kino")],
        [KeyboardButton(text="🔝 Top kinolar"), KeyboardButton(text="ℹ️ Bot haqida")]
    ]
    if is_admin(uid):
        k.append([KeyboardButton(text="⚡️ Admin Panel")])
    return ReplyKeyboardMarkup(keyboard=k, resize_keyboard=True, input_field_placeholder="Kino kodi...")

def sub_kb(channels: List[Dict[str, Any]], code: str = None) -> InlineKeyboardMarkup:
    btns = [[InlineKeyboardButton(text=f"📢 {c['title']}", url=c["invite_link"])] for c in channels]
    cb = f"check_sub:{code}" if code else "check_sub:"
    btns.append([InlineKeyboardButton(text="✅ Obunani tekshirish", callback_data=cb)])
    return InlineKeyboardMarkup(inline_keyboard=btns)

def admin_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Kino qo'shish", callback_data="adm:add"), InlineKeyboardButton(text="🗑 O'chirish", callback_data="adm:del")],
        [InlineKeyboardButton(text="📊 Statistika", callback_data="adm:stat"), InlineKeyboardButton(text="📢 Xabar yuborish", callback_data="adm:bc")],
        [InlineKeyboardButton(text="🔗 Homiy kanallar", callback_data="adm:ch")]
    ])

class UState(StatesGroup):
    search = State()

class AState(StatesGroup):
    file = State()
    code = State()
    title = State()
    desc = State()
    del_code = State()
    bc = State()
    ch_id = State()
    ch_title = State()
    ch_link = State()

dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)

async def send_movie(bot: Bot, cid: int, m: dict):
    await db.inc_views(m["code"])
    me = await bot.get_me()
    cap = f"🎬 <b>{m['title']}</b>\n🔢 Kod: <code>{m['code']}</code>\n👁 Ko'rishlar: {m['views'] + 1}\n\n"
    if m.get("description"):
        cap += f"📝 {m['description']}\n\n"
    cap += f"🤖 @{me.username}"
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="↗️ Ulashish", url=f"https://t.me/share/url?url=https://t.me/{me.username}?start={m['code']}&text=Kino+kodi:+{m['code']}") ]])
    if m.get("file_type") == "document":
        await bot.send_document(cid, document=m["file_id"], caption=cap, parse_mode="HTML", reply_markup=kb)
    else:
        await bot.send_video(cid, video=m["file_id"], caption=cap, parse_mode="HTML", reply_markup=kb)

@router.message(CommandStart())
async def cmd_start(msg: Message, bot: Bot, command: CommandStart, state: FSMContext):
    await state.clear()
    u = msg.from_user
    await db.add_user(u.id, u.username, u.full_name)
    code = command.args.strip() if command.args else None
    ok, unsubs = await check_subs(bot, u.id)
    if not ok:
        await msg.answer("⚠️ <b>Botdan foydalanish uchun quyidagi kanallarga obuna bo'ling:</b>", reply_markup=sub_kb(unsubs, code), parse_mode="HTML")
        return
    if code:
        m = await db.get_movie(code)
        if m:
            await send_movie(bot, msg.chat.id, m)
            return
    await msg.answer(f"👋 Assalomu alaykum, <b>{u.first_name}</b>!\n\n🎬 Kino kodini yuboring (masalan: <code>1</code>):", reply_markup=main_kb(u.id), parse_mode="HTML")

@router.callback_query(F.data.startswith("check_sub:"))
async def on_sub_click(cb: CallbackQuery, bot: Bot):
    code = cb.data.split("check_sub:")[1].strip()
    ok, unsubs = await check_subs(bot, cb.from_user.id)
    if not ok:
        await cb.answer("❌ Hali barcha kanallarga a'zo bo'lmadingiz!", show_alert=True)
        return
    await cb.answer("✅ Rahmat! Obuna tasdiqlandi.")
    try:
        await cb.message.delete()
    except Exception:
        pass
    if code:
        m = await db.get_movie(code)
        if m:
            await send_movie(bot, cb.from_user.id, m)
            return
    await bot.send_message(cb.from_user.id, "🎉 Xush kelibsiz! Kino kodini yuboring:", reply_markup=main_kb(cb.from_user.id))

@router.message(Command("admin"))
@router.message(F.text == "⚡️ Admin Panel")
async def adm_menu(msg: Message, state: FSMContext):
    if not is_admin(msg.from_user.id):
        return
    await state.clear()
    await msg.answer("🛠 <b>Boshqaruv paneli:</b>", reply_markup=admin_kb(), parse_mode="HTML")

@router.callback_query(F.data == "adm:stat")
async def adm_stat(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        return
    u, m, v = await db.get_stats()
    chs = await db.get_channels()
    await cb.message.edit_text(f"📊 <b>Statistika:</b>\n\n👥 Foydalanuvchilar: {u}\n🎬 Kinolar: {m}\n👁 Ko'rishlar: {v}\n📢 Kanallar: {len(chs)} ta", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Orqaga", callback_data="adm:back")]]), parse_mode="HTML")

@router.callback_query(F.data == "adm:back")
async def adm_back(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.edit_text("🛠 <b>Boshqaruv paneli:</b>", reply_markup=admin_kb(), parse_mode="HTML")

@router.callback_query(F.data == "adm:add")
async def adm_add(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    await state.set_state(AState.file)
    await cb.message.edit_text("📤 <b>1-qadam:</b> Kino videosini yoki faylini yuboring:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Bekor qilish", callback_data="adm:back")]]), parse_mode="HTML")

@router.message(AState.file, F.video | F.document)
async def adm_f(msg: Message, state: FSMContext):
    fid = msg.video.file_id if msg.video else msg.document.file_id
    ft = "video" if msg.video else "document"
    await state.update_data(fid=fid, ft=ft)
    nxt = await db.next_code()
    await state.set_state(AState.code)
    await msg.answer(f"🔢 <b>2-qadam:</b> Kino kodini kiriting (Tavsiya: <code>{nxt}</code>):", parse_mode="HTML")

@router.message(AState.code, F.text)
async def adm_c(msg: Message, state: FSMContext):
    c = msg.text.strip()
    if await db.get_movie(c):
        await msg.answer(f"⚠️ {c} kodi band! Boshqa kod kiriting:")
        return
    await state.update_data(code=c)
    await state.set_state(AState.title)
    await msg.answer("📝 <b>3-qadam:</b> Kino nomini kiriting:")

@router.message(AState.title, F.text)
async def adm_t(msg: Message, state: FSMContext):
    await state.update_data(title=msg.text.strip())
    await state.set_state(AState.desc)
    await msg.answer("📄 <b>4-qadam:</b> Tavsif kiriting yoki o'tkazib yuboring:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⏭ O'tkazib yuborish", callback_data="adm:skip_desc")]]))

@router.callback_query(AState.desc, F.data == "adm:skip_desc")
@router.message(AState.desc, F.text)
async def adm_d(evt: Any, state: FSMContext):
    data = await state.get_data()
    await state.clear()
    desc = evt.text.strip() if isinstance(evt, Message) else None
    ok = await db.add_movie(data["code"], data["title"], data["fid"], data["ft"], desc)
    m = evt if isinstance(evt, Message) else evt.message
    await m.answer(f"✅ Saqlandi!\n🎬 {data['title']}\n🔢 Kod: <code>{data['code']}</code>" if ok else "❌ Xatolik!", reply_markup=admin_kb(), parse_mode="HTML")

@router.callback_query(F.data == "adm:del")
async def adm_del(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    await state.set_state(AState.del_code)
    await cb.message.edit_text("🗑 O'chiriladigan kino kodini kiriting:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Bekor qilish", callback_data="adm:back")]]))

@router.message(AState.del_code, F.text)
async def adm_del_proc(msg: Message, state: FSMContext):
    ok = await db.del_movie(msg.text.strip())
    await state.clear()
    await msg.answer("✅ O'chirildi!" if ok else "❌ Topilmadi!", reply_markup=admin_kb())

@router.callback_query(F.data == "adm:bc")
async def adm_bc(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    await state.set_state(AState.bc)
    await cb.message.edit_text("📢 Barchaga yuboriladigan xabarni yuboring:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Bekor qilish", callback_data="adm:back")]]))

@router.message(AState.bc)
async def adm_bc_proc(msg: Message, state: FSMContext, bot: Bot):
    await state.clear()
    users = await db.get_all_users()
    s, f = 0, 0
    status_msg = await msg.answer(f"⏳ Tarqatilmoqda (0/{len(users)})...")
    for idx, uid in enumerate(users, 1):
        try:
            await msg.copy_to(uid)
            s += 1
        except Exception:
            f += 1
        if idx % 25 == 0:
            try:
                await status_msg.edit_text(f"⏳ ({idx}/{len(users)})\nYetdi: {s} | Xato: {f}")
            except Exception:
                pass
        await asyncio.sleep(0.05)
    await status_msg.edit_text(f"✅ Tayyor!\n👥 Jami: {len(users)}\n🟢 Yetdi: {s}\n🔴 Blok: {f}")

@router.callback_query(F.data == "adm:ch")
async def adm_ch_list(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        return
    chs = await db.get_channels()
    b = [[InlineKeyboardButton(text=f"❌ {c['title']}", callback_data=f"adm:del_ch:{c['channel_id']}")] for c in chs]
    b.append([InlineKeyboardButton(text="➕ Kanal qo'shish", callback_data="adm:add_ch")])
    b.append([InlineKeyboardButton(text="🔙 Orqaga", callback_data="adm:back")])
    await cb.message.edit_text("🔗 <b>Homiy kanallar:</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=b), parse_mode="HTML")

@router.callback_query(F.data.startswith("adm:del_ch:"))
async def adm_del_ch(cb: CallbackQuery):
    cid = cb.data.split("adm:del_ch:")[1]
    await db.del_channel(cid)
    await cb.answer("O'chirildi!")
    await adm_ch_list(cb)

@router.callback_query(F.data == "adm:add_ch")
async def adm_add_ch_prompt(cb: CallbackQuery, state: FSMContext):
    await state.set_state(AState.ch_id)
    await cb.message.edit_text("📢 Kanal username'ini yuboring (masalan: <code>@kanal</code>) yoki kanaldan post uzating:\n<i>(Bot u yerda admin bo'lishi shart!)</i>", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Bekor qilish", callback_data="adm:ch")]]), parse_mode="HTML")

@router.message(AState.ch_id)
async def adm_add_ch_proc(msg: Message, state: FSMContext, bot: Bot):
    raw = ""
    if msg.forward_origin and hasattr(msg.forward_origin, "chat"):
        raw = str(msg.forward_origin.chat.id)
    elif msg.forward_from_chat:
        raw = str(msg.forward_from_chat.id)
    elif msg.text:
        raw = msg.text.replace("https://t.me/", "").replace("+", "").replace("/", "").strip()
        if not raw.startswith("@") and not raw.startswith("-"):
            raw = f"@{raw}"
    try:
        chat = await bot.get_chat(parse_cid(raw))
        me = await bot.get_me()
        m = await bot.get_chat_member(chat.id, me.id)
        if m.status not in ["administrator", "creator"]:
            await msg.answer("⚠️ Bot bu kanalda admin emas! Avval admin qiling.")
            return
        link = f"https://t.me/{chat.username}" if chat.username else (chat.invite_link or f"https://t.me/{raw.lstrip('@')}")
        await db.add_channel(str(chat.id) if not chat.username else f"@{chat.username}", chat.title, link)
        await state.clear()
        await msg.answer(f"✅ Kanal qo'shildi!\n📢 {chat.title}\n🔗 {link}", reply_markup=admin_kb())
    except Exception as e:
        logger.warning(f"Ch add err: {e}")
        await msg.answer("❌ Kanal topilmadi. Qaytadan urinib ko'ring:")

@router.message(F.text == "🔍 Kino qidirish")
async def u_search(msg: Message, state: FSMContext):
    await state.set_state(UState.search)
    await msg.answer("🔍 Kino nomini kiriting:", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="❌ Bekor qilish")]], resize_keyboard=True))

@router.message(F.text == "❌ Bekor qilish")
async def u_cancel(msg: Message, state: FSMContext):
    await state.clear()
    await msg.answer("Bekor qilindi.", reply_markup=main_kb(msg.from_user.id))

@router.message(UState.search)
async def u_search_p(msg: Message, state: FSMContext):
    await state.clear()
    res = await db.search_movies(msg.text.strip(), 10)
    if not res:
        await msg.answer("😔 Kino topilmadi.", reply_markup=main_kb(msg.from_user.id))
        return
    t = f"🔎 <b>Natijalar:</b>\n\n" + "\n".join([f"🔹 <b>{r['title']}</b> — Kod: <code>{r['code']}</code> (👁 {r['views']})" for r in res]) + "\n\n💡 Yuklash uchun kino kodini yuboring!"
    await msg.answer(t, reply_markup=main_kb(msg.from_user.id), parse_mode="HTML")

@router.message(F.text == "🎲 Tasodifiy kino")
async def u_rand(msg: Message, bot: Bot):
    m = await db.get_random()
    if m:
        await send_movie(bot, msg.chat.id, m)
    else:
        await msg.answer("Kinolar hali yo'q.")

@router.message(F.text == "🔝 Top kinolar")
async def u_top(msg: Message):
    tops = await db.get_top(10)
    if not tops:
        await msg.answer("Kinolar yo'q.")
        return
    t = "🔥 <b>TOP Kinolar:</b>\n\n" + "\n".join([f"{i}. <b>{m['title']}</b> (Kod: <code>{m['code']}</code> | 👁 {m['views']})" for i, m in enumerate(tops, 1)]) + "\n\n💡 Yuklash uchun kodni yuboring."
    await msg.answer(t, parse_mode="HTML")

@router.message(F.text == "ℹ️ Bot haqida")
async def u_info(msg: Message):
    _, m, _ = await db.get_stats()
    await msg.answer(f"ℹ️ <b>@Islomovkinobot</b>\n\nKino kodini yuboring va darhol yuklab oling!\n🎬 Kinolar soni: {m} ta", parse_mode="HTML")

@router.message(F.text)
async def u_code(msg: Message, bot: Bot):
    c = msg.text.strip()
    ok, unsubs = await check_subs(bot, msg.from_user.id)
    if not ok:
        await msg.answer("⚠️ Botdan foydalanish uchun homiy kanallarga obuna bo'ling!", reply_markup=sub_kb(unsubs, c))
        return
    m = await db.get_movie(c)
    if m:
        await send_movie(bot, msg.chat.id, m)
        return
    res = await db.search_movies(c, 5)
    if res:
        t = f"❌ <code>{c}</code> kodi topilmadi.\n\n🔎 O'xshash kinolar:\n" + "\n".join([f"🔹 <b>{r['title']}</b> — Kod: <code>{r['code']}</code>" for r in res]) + "\n\nKino kodini yuboring."
        await msg.answer(t, parse_mode="HTML")
    else:
        await msg.answer(f"❌ <code>{c}</code> kodi topilmadi.", parse_mode="HTML")

async def start_web():
    port_env = os.getenv("PORT")
    if not port_env:
        return
    from aiohttp import web
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="Bot is running!"))
    app.router.add_get("/health", lambda r: web.Response(text="OK"))
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", int(port_env)).start()
    logger.info(f"Healthcheck on port {port_env}")

async def main():
    if not BOT_TOKEN:
        sys.exit(1)
    await start_web()
    await db.init_db()
    bot = Bot(token=BOT_TOKEN)
    await bot.set_my_commands([BotCommand(command="start", description="Qayta ishga tushirish"), BotCommand(command="admin", description="Admin panel")])
    for ch in CONFIG_CHANNELS:
        try:
            c = await bot.get_chat(parse_cid(ch))
            lnk = f"https://t.me/{c.username}" if c.username else (c.invite_link or f"https://t.me/{ch.lstrip('@')}")
            await db.add_channel(str(c.id) if not c.username else f"@{c.username}", c.title or ch, lnk)
        except Exception:
            pass
    logger.info("Bot starting polling...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
