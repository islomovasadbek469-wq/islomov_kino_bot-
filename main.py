import os
import sys
import asyncio
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, F, Router
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message,
    CallbackQuery,
    BotCommand,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
import aiosqlite

# --- Configuration ---
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

# Admin IDs
_admins_str = os.getenv("ADMINS", "").strip()
ADMIN_IDS = set()
if _admins_str:
    for item in _admins_str.split(","):
        cleaned = item.strip()
        if cleaned.isdigit():
            ADMIN_IDS.add(int(cleaned))

# Channels from config
_channels_str = os.getenv("CHANNELS", "").strip()
CONFIG_CHANNELS = []
if _channels_str:
    for item in _channels_str.split(","):
        cleaned = item.strip()
        if cleaned:
            CONFIG_CHANNELS.append(cleaned)

DB_PATH = BASE_DIR / os.getenv("DB_PATH", "data/kino_bot.db")
DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


# --- Logging ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("IslomovKinoBot")


# --- Database Layer ---
class Database:
    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path

    async def init_db(self):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    full_name TEXT,
                    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS movies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code TEXT UNIQUE NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT,
                    file_id TEXT NOT NULL,
                    file_type TEXT DEFAULT 'video',
                    views INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS channels (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_id TEXT UNIQUE NOT NULL,
                    title TEXT NOT NULL,
                    invite_link TEXT NOT NULL
                )
                """
            )
            await db.commit()

    async def add_user(self, user_id: int, username: Optional[str], full_name: Optional[str]):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO users (user_id, username, full_name)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    username=excluded.username,
                    full_name=excluded.full_name
                """,
                (user_id, username, full_name),
            )
            await db.commit()

    async def get_user_count(self) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT COUNT(*) FROM users") as cursor:
                row = await cursor.fetchone()
                return row[0] if row else 0

    async def get_all_user_ids(self) -> List[int]:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT user_id FROM users") as cursor:
                rows = await cursor.fetchall()
                return [row[0] for row in rows]

    async def add_movie(
        self,
        code: str,
        title: str,
        file_id: str,
        file_type: str = "video",
        description: Optional[str] = None,
    ) -> bool:
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    """
                    INSERT INTO movies (code, title, description, file_id, file_type)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (code.strip(), title.strip(), description, file_id, file_type),
                )
                await db.commit()
                return True
        except aiosqlite.IntegrityError:
            return False

    async def get_movie_by_code(self, code: str) -> Optional[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM movies WHERE code = ?", (code.strip(),)
            ) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def increment_views(self, code: str):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE movies SET views = views + 1 WHERE code = ?",
                (code.strip(),),
            )
            await db.commit()

    async def delete_movie(self, code: str) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "DELETE FROM movies WHERE code = ?", (code.strip(),)
            )
            await db.commit()
            return cursor.rowcount > 0

    async def search_movies(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        search_pattern = f"%{query.strip()}%"
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT code, title, views FROM movies
                WHERE title LIKE ? OR description LIKE ?
                ORDER BY views DESC LIMIT ?
                """,
                (search_pattern, search_pattern, limit),
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(r) for r in rows]

    async def get_random_movie(self) -> Optional[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM movies ORDER BY RANDOM() LIMIT 1"
            ) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def get_top_movies(self, limit: int = 10) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT code, title, views FROM movies ORDER BY views DESC LIMIT ?",
                (limit,),
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(r) for r in rows]

    async def get_movie_count(self) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT COUNT(*) FROM movies") as cursor:
                row = await cursor.fetchone()
                return row[0] if row else 0

    async def get_total_views(self) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT COALESCE(SUM(views), 0) FROM movies") as cursor:
                row = await cursor.fetchone()
                return row[0] if row else 0

    async def get_next_suggested_code(self) -> str:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT MAX(CAST(code AS INTEGER)) FROM movies WHERE code GLOB '[0-9]*'"
            ) as cursor:
                row = await cursor.fetchone()
                if row and row[0] is not None:
                    return str(row[0] + 1)
                return "1"

    async def add_channel(self, channel_id: str, title: str, invite_link: str) -> bool:
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    """
                    INSERT INTO channels (channel_id, title, invite_link)
                    VALUES (?, ?, ?)
                    ON CONFLICT(channel_id) DO UPDATE SET
                        title=excluded.title,
                        invite_link=excluded.invite_link
                    """,
                    (channel_id.strip(), title.strip(), invite_link.strip()),
                )
                await db.commit()
                return True
        except Exception:
            return False

    async def remove_channel(self, channel_id: str) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "DELETE FROM channels WHERE channel_id = ?", (channel_id.strip(),)
            )
            await db.commit()
            return cursor.rowcount > 0

    async def get_all_channels(self) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM channels") as cursor:
                rows = await cursor.fetchall()
                return [dict(r) for r in rows]


db = Database()


# --- Subscriptions Verification ---
def parse_chat_id(channel_id: str):
    clean = channel_id.strip()
    if (clean.startswith("-") and clean[1:].isdigit()) or clean.isdigit():
        return int(clean)
    return clean


async def check_user_subscriptions(
    bot: Bot, user_id: int
) -> Tuple[bool, List[Dict[str, Any]]]:
    channels = await db.get_all_channels()
    if not channels:
        return True, []

    unsubscribed = []
    for channel in channels:
        raw_id = channel["channel_id"]
        chat_ref = parse_chat_id(raw_id)
        try:
            member = await bot.get_chat_member(chat_id=chat_ref, user_id=user_id)
            if member.status in [ChatMemberStatus.LEFT, ChatMemberStatus.KICKED]:
                unsubscribed.append(channel)
        except TelegramBadRequest as e:
            err_msg = str(e).lower()
            if any(k in err_msg for k in ["user not found", "user_not_participant", "participant_id_invalid"]):
                unsubscribed.append(channel)
            else:
                logger.warning(f"TelegramBadRequest checking channel {raw_id}: {e}")
        except Exception as e:
            logger.warning(f"Error checking chat member for channel {raw_id}: {e}")

    return len(unsubscribed) == 0, unsubscribed


# --- Keyboards ---
def get_main_menu_keyboard(user_id: int) -> ReplyKeyboardMarkup:
    keyboard = [
        [KeyboardButton(text="🔍 Kino qidirish"), KeyboardButton(text="🎲 Tasodifiy kino")],
        [KeyboardButton(text="🔝 Top kinolar"), KeyboardButton(text="ℹ️ Bot haqida")],
    ]
    if is_admin(user_id):
        keyboard.append([KeyboardButton(text="⚡️ Admin Panel")])
    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
        input_field_placeholder="Kino kodini yuboring (masalan: 1)...",
    )


def get_cancel_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Bekor qilish")]],
        resize_keyboard=True,
    )


def get_subscription_keyboard(
    channels: List[Dict[str, Any]], target_code: Optional[str] = None
) -> InlineKeyboardMarkup:
    keyboard = []
    for ch in channels:
        keyboard.append([InlineKeyboardButton(text=f"📢 {ch['title']}", url=ch["invite_link"])])
    callback_data = f"check_sub:{target_code}" if target_code else "check_sub:"
    keyboard.append([InlineKeyboardButton(text="✅ Obunani tekshirish", callback_data=callback_data)])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_admin_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton(text="➕ Kino qo'shish", callback_data="admin:add_movie"),
            InlineKeyboardButton(text="🗑 Kino o'chirish", callback_data="admin:delete_movie"),
        ],
        [
            InlineKeyboardButton(text="📊 Statistika", callback_data="admin:stats"),
            InlineKeyboardButton(text="📢 Xabar yuborish", callback_data="admin:broadcast"),
        ],
        [InlineKeyboardButton(text="🔗 Homiy kanallar", callback_data="admin:channels")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_channels_management_keyboard(channels: List[Dict[str, Any]]) -> InlineKeyboardMarkup:
    keyboard = []
    for ch in channels:
        keyboard.append([InlineKeyboardButton(text=f"❌ {ch['title']}", callback_data=f"admin:del_channel:{ch['channel_id']}")])
    keyboard.append([InlineKeyboardButton(text="➕ Yangi kanal qo'shish", callback_data="admin:add_channel")])
    keyboard.append([InlineKeyboardButton(text="🔙 Bosh menyu", callback_data="admin:back_to_menu")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_movie_share_keyboard(code: str, bot_username: str) -> InlineKeyboardMarkup:
    share_url = f"https://t.me/share/url?url=https://t.me/{bot_username}?start={code}&text=🎬+Ushbu+kinoni+tomosha+qiling!+Kodi:+{code}"
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="↗️ Do'stlarga ulashish", url=share_url)]])


# --- State Groups ---
class UserStates(StatesGroup):
    waiting_for_search_query = State()


class AdminStates(StatesGroup):
    waiting_for_movie_file = State()
    waiting_for_movie_code = State()
    waiting_for_movie_title = State()
    waiting_for_movie_desc = State()
    waiting_for_delete_code = State()
    waiting_for_broadcast_message = State()
    waiting_for_channel_id = State()
    waiting_for_channel_title = State()
    waiting_for_channel_link = State()


# --- Handlers: Subscription Check Callback ---
sub_router = Router()


@sub_router.callback_query(F.data.startswith("check_sub:"))
async def handle_sub_check(callback: CallbackQuery, bot: Bot):
    user_id = callback.from_user.id
    target_code = callback.data.split("check_sub:")[1].strip()

    is_subscribed, unsubscribed = await check_user_subscriptions(bot, user_id)
    if not is_subscribed:
        await callback.answer(
            "❌ Hali barcha kanallarga obuna bo'lmadingiz. Iltimos, obuna bo'lib qaytadan urinib ko'ring.",
            show_alert=True,
        )
        return

    await callback.answer("✅ Obuna tasdiqlandi!", show_alert=False)
    try:
        await callback.message.delete()
    except Exception:
        pass

    bot_info = await bot.get_me()
    if target_code:
        movie = await db.get_movie_by_code(target_code)
        if movie:
            await send_movie_to_user(bot, user_id, movie)
            return

    await bot.send_message(
        chat_id=user_id,
        text="🎉 <b>Xush kelibsiz!</b>\n\nKino kodini yuboring yoki quyidagi menyudan foydalaning:",
        parse_mode="HTML",
        reply_markup=get_main_menu_keyboard(user_id),
    )


# --- Handlers: Admin Panel ---
admin_router = Router()


@admin_router.message(Command("admin"))
async def admin_panel(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.clear()
    await message.answer(
        "🛠 <b>Boshqaruv paneli (Admin Panel):</b>\n\nKerakli bo'limni tanlang:",
        reply_markup=get_admin_keyboard(),
        parse_mode="HTML",
    )


@admin_router.callback_query(F.data == "admin:back_to_menu")
async def back_to_admin_menu(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await state.clear()
    await callback.message.edit_text(
        "🛠 <b>Boshqaruv paneli (Admin Panel):</b>\n\nKerakli bo'limni tanlang:",
        reply_markup=get_admin_keyboard(),
        parse_mode="HTML",
    )


@admin_router.callback_query(F.data == "admin:stats")
async def show_stats(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    total_users = await db.get_user_count()
    total_movies = await db.get_movie_count()
    total_views = await db.get_total_views()
    channels = await db.get_all_channels()

    text = (
        "📊 <b>Bot Statistikasi:</b>\n\n"
        f"👥 <b>Foydalanuvchilar:</b> {total_users} ta\n"
        f"🎬 <b>Yuklangan kinolar:</b> {total_movies} ta\n"
        f"👁 <b>Umumiy ko'rishlar:</b> {total_views} marta\n"
        f"📢 <b>Homiy kanallar:</b> {len(channels)} ta\n"
    )
    back_kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🔙 Orqaga", callback_data="admin:back_to_menu")]]
    )
    await callback.message.edit_text(text, reply_markup=back_kb, parse_mode="HTML")


@admin_router.callback_query(F.data == "admin:add_movie")
async def start_add_movie(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await state.set_state(AdminStates.waiting_for_movie_file)
    cancel_kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="❌ Bekor qilish", callback_data="admin:back_to_menu")]]
    )
    await callback.message.edit_text(
        "📤 <b>1-qadam:</b> Kinoning video yoki faylini yuboring:",
        reply_markup=cancel_kb,
        parse_mode="HTML",
    )


@admin_router.message(AdminStates.waiting_for_movie_file, F.video | F.document)
async def process_movie_file(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    file_id = message.video.file_id if message.video else message.document.file_id
    file_type = "video" if message.video else "document"

    await state.update_data(file_id=file_id, file_type=file_type)
    suggested_code = await db.get_next_suggested_code()
    await state.set_state(AdminStates.waiting_for_movie_code)

    cancel_kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="❌ Bekor qilish", callback_data="admin:back_to_menu")]]
    )
    await message.answer(
        f"🔢 <b>2-qadam:</b> Kino kodini kiriting.\n\n<i>Tavsiya etilgan kod:</i> <code>{suggested_code}</code>",
        reply_markup=cancel_kb,
        parse_mode="HTML",
    )


@admin_router.message(AdminStates.waiting_for_movie_code, F.text)
async def process_movie_code(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    code = message.text.strip()
    existing = await db.get_movie_by_code(code)
    if existing:
        await message.answer(
            f"⚠️ <b>{code}</b> kodi allaqachon mavjud («{existing['title']}»)! Boshqa kod kiriting:",
            parse_mode="HTML",
        )
        return

    await state.update_data(code=code)
    await state.set_state(AdminStates.waiting_for_movie_title)
    cancel_kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="❌ Bekor qilish", callback_data="admin:back_to_menu")]]
    )
    await message.answer("📝 <b>3-qadam:</b> Kino nomini kiriting:", reply_markup=cancel_kb, parse_mode="HTML")


@admin_router.message(AdminStates.waiting_for_movie_title, F.text)
async def process_movie_title(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    title = message.text.strip()
    await state.update_data(title=title)
    await state.set_state(AdminStates.waiting_for_movie_desc)

    skip_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⏭ O'tkazib yuborish", callback_data="admin:skip_desc")],
            [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="admin:back_to_menu")],
        ]
    )
    await message.answer(
        "📄 <b>4-qadam:</b> Kino tavsifini kiriting (yoki o'tkazib yuboring):",
        reply_markup=skip_kb,
        parse_mode="HTML",
    )


@admin_router.callback_query(AdminStates.waiting_for_movie_desc, F.data == "admin:skip_desc")
async def process_movie_skip_desc(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await finish_add_movie(callback.message, data, description=None)
    await state.clear()


@admin_router.message(AdminStates.waiting_for_movie_desc, F.text)
async def process_movie_desc(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    data = await state.get_data()
    await finish_add_movie(message, data, description=message.text.strip())
    await state.clear()


async def finish_add_movie(message: Message, data: dict, description: str = None):
    success = await db.add_movie(
        code=data["code"],
        title=data["title"],
        file_id=data["file_id"],
        file_type=data["file_type"],
        description=description,
    )
    if success:
        text = f"✅ <b>Kino saqlandi!</b>\n\n🎬 {data['title']}\n🔢 Kod: <code>{data['code']}</code>"
    else:
        text = "❌ Xatolik yuz berdi."
    await message.answer(text, reply_markup=get_admin_keyboard(), parse_mode="HTML")


@admin_router.callback_query(F.data == "admin:delete_movie")
async def start_delete_movie(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await state.set_state(AdminStates.waiting_for_delete_code)
    cancel_kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="❌ Bekor qilish", callback_data="admin:back_to_menu")]]
    )
    await callback.message.edit_text("🗑 O'chirmoqchi bo'lgan <b>kino kodini</b> yuboring:", reply_markup=cancel_kb, parse_mode="HTML")


@admin_router.message(AdminStates.waiting_for_delete_code, F.text)
async def process_delete_code(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    code = message.text.strip()
    deleted = await db.delete_movie(code)
    await state.clear()
    if deleted:
        await message.answer(f"✅ <code>{code}</code> kodli kino o'chirildi.", reply_markup=get_admin_keyboard(), parse_mode="HTML")
    else:
        await message.answer(f"❌ <code>{code}</code> kodli kino topilmadi.", reply_markup=get_admin_keyboard(), parse_mode="HTML")


@admin_router.callback_query(F.data == "admin:broadcast")
async def start_broadcast(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await state.set_state(AdminStates.waiting_for_broadcast_message)
    cancel_kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="❌ Bekor qilish", callback_data="admin:back_to_menu")]]
    )
    await callback.message.edit_text("📢 Barcha foydalanuvchilarga yubormoqchi bo'lgan xabarni yuboring:", reply_markup=cancel_kb)


@admin_router.message(AdminStates.waiting_for_broadcast_message)
async def process_broadcast_message(message: Message, state: FSMContext, bot: Bot):
    if not is_admin(message.from_user.id):
        return
    await state.clear()
    users = await db.get_all_user_ids()
    total = len(users)
    if total == 0:
        await message.answer("Foydalanuvchilar mavjud emas.", reply_markup=get_admin_keyboard())
        return

    status_msg = await message.answer(f"⏳ Xabar tarqatilmoqda (0/{total})...")
    sent, failed = 0, 0
    for idx, uid in enumerate(users, 1):
        try:
            await message.copy_to(chat_id=uid)
            sent += 1
        except Exception:
            failed += 1
        if idx % 25 == 0:
            try:
                await status_msg.edit_text(f"⏳ Xabar tarqatilmoqda ({idx}/{total})...\nYetkazildi: {sent} | Xatolik: {failed}")
            except Exception:
                pass
        await asyncio.sleep(0.05)

    try:
        await status_msg.delete()
    except Exception:
        pass
    await message.answer(f"✅ Yakunlandi!\n👥 Jami: {total}\n🟢 Yetkazildi: {sent}\n🔴 Bloklagan: {failed}", reply_markup=get_admin_keyboard())


@admin_router.callback_query(F.data == "admin:channels")
async def show_channels_management(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    channels = await db.get_all_channels()
    text = "🔗 <b>Homiy kanallar:</b>\n\n"
    if channels:
        for idx, ch in enumerate(channels, 1):
            text += f"{idx}. <b>{ch['title']}</b> ({ch['channel_id']})\n   🔗 {ch['invite_link']}\n"
    else:
        text += "Hozircha kanallar yo'q."
    await callback.message.edit_text(text, reply_markup=get_channels_management_keyboard(channels), parse_mode="HTML")


@admin_router.callback_query(F.data.startswith("admin:del_channel:"))
async def delete_channel(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    cid = callback.data.split("admin:del_channel:")[1]
    await db.remove_channel(cid)
    await callback.answer("Kanal o'chirildi!", show_alert=True)
    await show_channels_management(callback)


@admin_router.callback_query(F.data == "admin:add_channel")
async def start_add_channel(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await state.set_state(AdminStates.waiting_for_channel_id)
    cancel_kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="❌ Bekor qilish", callback_data="admin:channels")]]
    )
    await callback.message.edit_text(
        "📢 <b>Kanal qo'shish:</b>\n\n"
        "1. Avval botni (@Islomovkinobot) kanalingizga <b>ADMIN</b> qiling.\n"
        "2. So'ngra kanaldan post uzating yoki <code>@kanal</code> yuboring:",
        reply_markup=cancel_kb,
        parse_mode="HTML",
    )


@admin_router.message(AdminStates.waiting_for_channel_id)
async def process_channel_id(message: Message, state: FSMContext, bot: Bot):
    if not is_admin(message.from_user.id):
        return
    raw_input = ""
    if message.forward_origin and hasattr(message.forward_origin, "chat"):
        raw_input = str(message.forward_origin.chat.id)
    elif message.forward_from_chat:
        raw_input = str(message.forward_from_chat.id)
    elif message.text:
        text = message.text.strip()
        if "t.me/" in text:
            parts = text.split("t.me/")[-1].replace("+", "").replace("/", "").strip()
            raw_input = f"@{parts}" if not parts.startswith("@") else parts
        else:
            raw_input = text

    if not raw_input:
        await message.answer("Iltimos, kanal username'ini yuboring yoki post uzating.")
        return

    chat_ref = parse_chat_id(raw_input)
    try:
        chat = await bot.get_chat(chat_ref)
        bot_user = await bot.get_me()
        member = await bot.get_chat_member(chat.id, bot_user.id)
        if member.status not in ["administrator", "creator"]:
            await message.answer(f"⚠️ Bot <b>{chat.title}</b> kanalida admin emas! Avval botni admin qiling.", parse_mode="HTML")
            return

        title = chat.title
        cid = str(chat.id)
        link = f"https://t.me/{chat.username}" if chat.username else (chat.invite_link or f"https://t.me/{raw_input.lstrip('@')}")
        await db.add_channel(channel_id=cid, title=title, invite_link=link)
        await state.clear()
        await message.answer(f"✅ <b>Kanal qo'shildi!</b>\n\n📢 {title}\n🆔 <code>{cid}</code>\n🔗 {link}", reply_markup=get_admin_keyboard(), parse_mode="HTML")
    except Exception as e:
        logger.warning(f"Error resolving channel {raw_input}: {e}")
        await state.update_data(channel_id=str(chat_ref))
        await state.set_state(AdminStates.waiting_for_channel_title)
        cancel_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Bekor qilish", callback_data="admin:channels")]])
        await message.answer("📝 Kanal nomini qo'lda kiriting:", reply_markup=cancel_kb)


@admin_router.message(AdminStates.waiting_for_channel_title, F.text)
async def process_channel_title(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.update_data(channel_title=message.text.strip())
    await state.set_state(AdminStates.waiting_for_channel_link)
    cancel_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Bekor qilish", callback_data="admin:channels")]])
    await message.answer("🔗 Kanalga kirish havolasini (link) yuboring:", reply_markup=cancel_kb)


@admin_router.message(AdminStates.waiting_for_channel_link, F.text)
async def process_channel_link(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    link = message.text.strip()
    data = await state.get_data()
    await state.clear()
    await db.add_channel(channel_id=data["channel_id"], title=data["channel_title"], invite_link=link)
    await message.answer(f"✅ Kanal qo'shildi!\n\n📢 {data['channel_title']}\n🔗 {link}", reply_markup=get_admin_keyboard())


# --- Handlers: User Commands and Search ---
user_router = Router()


async def send_movie_to_user(bot: Bot, chat_id: int, movie: dict):
    await db.increment_views(movie["code"])
    bot_info = await bot.get_me()
    caption = (
        f"🎬 <b>{movie['title']}</b>\n"
        f"🔢 <b>Kino kodi:</b> <code>{movie['code']}</code>\n"
        f"👁 <b>Ko'rishlar:</b> {movie['views'] + 1}\n\n"
    )
    if movie.get("description"):
        caption += f"📝 <b>Tavsif:</b>\n{movie['description']}\n\n"
    caption += f"🤖 <b>Bot:</b> @{bot_info.username}"
    share_kb = get_movie_share_keyboard(movie["code"], bot_info.username)

    if movie.get("file_type") == "document":
        await bot.send_document(chat_id=chat_id, document=movie["file_id"], caption=caption, parse_mode="HTML", reply_markup=share_kb)
    else:
        await bot.send_video(chat_id=chat_id, video=movie["file_id"], caption=caption, parse_mode="HTML", reply_markup=share_kb)


@user_router.message(CommandStart())
async def handle_start(message: Message, bot: Bot, command: CommandStart, state: FSMContext):
    await state.clear()
    user = message.from_user
    await db.add_user(user.id, user.username, user.full_name)
    target_code = command.args.strip() if command.args else None

    is_sub, unsubs = await check_user_subscriptions(bot, user.id)
    if not is_sub:
        await message.answer(
            "⚠️ <b>Botdan foydalanish uchun quyidagi kanallarga obuna bo'ling:</b>\n\n"
            "So'ng <b>«✅ Obunani tekshirish»</b> tugmasini bosing.",
            reply_markup=get_subscription_keyboard(unsubs, target_code=target_code),
            parse_mode="HTML",
        )
        return

    if target_code:
        movie = await db.get_movie_by_code(target_code)
        if movie:
            await send_movie_to_user(bot, message.chat.id, movie)
            return

    await message.answer(
        f"👋 Assalomu alaykum, <b>{user.first_name}</b>!\n\n"
        f"🎬 <b>@Islomovkinobot</b> ga xush kelibsiz!\n\n"
        "📥 Kino kodini yuboring (masalan: <code>1</code>) yoki quyidagi menyudan foydalaning:",
        reply_markup=get_main_menu_keyboard(user.id),
        parse_mode="HTML",
    )


@user_router.message(F.text == "❌ Bekor qilish")
async def cancel_handler(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Bekor qilindi.", reply_markup=get_main_menu_keyboard(message.from_user.id))


@user_router.message(F.text == "🔍 Kino qidirish")
async def search_movie_prompt(message: Message, state: FSMContext, bot: Bot):
    is_sub, unsubs = await check_user_subscriptions(bot, message.from_user.id)
    if not is_sub:
        await message.answer("⚠️ Botdan foydalanish uchun homiy kanallarga obuna bo'ling!", reply_markup=get_subscription_keyboard(unsubs))
        return
    await state.set_state(UserStates.waiting_for_search_query)
    await message.answer("🔍 Qidirayotgan kinongiz nomini kiriting:", reply_markup=get_cancel_keyboard())


@user_router.message(UserStates.waiting_for_search_query)
async def process_search_query(message: Message, state: FSMContext):
    query = message.text.strip()
    results = await db.search_movies(query, limit=10)
    await state.clear()
    if not results:
        await message.answer(f"😔 «{query}» bo'yicha kino topilmadi.", reply_markup=get_main_menu_keyboard(message.from_user.id))
        return
    text = f"🔎 <b>«{query}» bo'yicha topilgan kinolar:</b>\n\n"
    for r in results:
        text += f"🔹 <b>{r['title']}</b> — Kod: <code>{r['code']}</code> (👁 {r['views']})\n"
    text += "\n💡 Kinoni yuklash uchun uning <b>kodini</b> yuboring!"
    await message.answer(text, reply_markup=get_main_menu_keyboard(message.from_user.id), parse_mode="HTML")


@user_router.message(F.text == "🎲 Tasodifiy kino")
async def random_movie_handler(message: Message, bot: Bot):
    is_sub, unsubs = await check_user_subscriptions(bot, message.from_user.id)
    if not is_sub:
        await message.answer("⚠️ Homiy kanallarga obuna bo'ling!", reply_markup=get_subscription_keyboard(unsubs))
        return
    movie = await db.get_random_movie()
    if not movie:
        await message.answer("Hozircha kinolar mavjud emas.")
        return
    await send_movie_to_user(bot, message.chat.id, movie)


@user_router.message(F.text == "🔝 Top kinolar")
async def top_movies_handler(message: Message, bot: Bot):
    is_sub, unsubs = await check_user_subscriptions(bot, message.from_user.id)
    if not is_sub:
        await message.answer("⚠️ Homiy kanallarga obuna bo'ling!", reply_markup=get_subscription_keyboard(unsubs))
        return
    top_list = await db.get_top_movies(limit=10)
    if not top_list:
        await message.answer("Hozircha kinolar mavjud emas.")
        return
    text = "🔥 <b>TOP kinolar:</b>\n\n"
    for idx, m in enumerate(top_list, 1):
        text += f"{idx}. <b>{m['title']}</b> (Kod: <code>{m['code']}</code> | 👁 {m['views']})\n"
    text += "\n💡 Yuklash uchun kino kodini yozib yuboring."
    await message.answer(text, parse_mode="HTML")


@user_router.message(F.text == "ℹ️ Bot haqida")
async def about_bot_handler(message: Message):
    total_movies = await db.get_movie_count()
    await message.answer(
        f"ℹ️ <b>@Islomovkinobot</b>\n\n"
        f"Filmlarni kod orqali tezkor yuklab olish boti.\n"
        f"🎬 Kinolar soni: {total_movies} ta\n\n"
        f"Kino kodini yozib yuboring va darhol tomosha qiling!",
        parse_mode="HTML",
    )


@user_router.message(F.text == "⚡️ Admin Panel")
async def admin_shortcut_handler(message: Message):
    if not is_admin(message.from_user.id):
        return
    await message.answer("🛠 <b>Boshqaruv paneli:</b>", reply_markup=get_admin_keyboard(), parse_mode="HTML")


@user_router.message(F.text)
async def handle_code_input(message: Message, bot: Bot):
    user_id = message.from_user.id
    code_input = message.text.strip()
    is_sub, unsubs = await check_user_subscriptions(bot, user_id)
    if not is_sub:
        await message.answer(
            "⚠️ Botdan foydalanish uchun homiy kanallarga obuna bo'ling!",
            reply_markup=get_subscription_keyboard(unsubs, target_code=code_input),
        )
        return

    movie = await db.get_movie_by_code(code_input)
    if movie:
        await send_movie_to_user(bot, message.chat.id, movie)
        return

    search_results = await db.search_movies(code_input, limit=5)
    if search_results:
        text = f"❌ <code>{code_input}</code> kodi topilmadi.\n\n🔎 O'xshash kinolar:\n"
        for r in search_results:
            text += f"🔹 <b>{r['title']}</b> — Kod: <code>{r['code']}</code>\n"
        text += "\nKinoni olish uchun uning kodini yuboring."
        await message.answer(text, parse_mode="HTML")
    else:
        await message.answer(f"❌ <b>{code_input}</b> kodi bo'yicha kino topilmadi.", parse_mode="HTML")


# --- Cloud Web Healthcheck Server ---
async def start_healthcheck_server():
    port_env = os.getenv("PORT")
    if not port_env:
        return
    from aiohttp import web
    port = int(port_env)

    async def handle_ping(request):
        return web.Response(text="Bot is running!")

    app = web.Application()
    app.router.add_get("/", handle_ping)
    app.router.add_get("/health", handle_ping)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"Healthcheck web server started on port {port}")


# --- Main Entry Point ---
async def set_default_commands(bot: Bot):
    commands = [
        BotCommand(command="start", description="Botni qayta ishga tushirish"),
        BotCommand(command="admin", description="Admin panel"),
    ]
    await bot.set_my_commands(commands)


async def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN is not configured! Check your .env or environment variables.")
        sys.exit(1)

    await start_healthcheck_server()

    logger.info("Initializing database...")
    await db.init_db()

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())

    dp.include_router(admin_router)
    dp.include_router(sub_router)
    dp.include_router(user_router)

    await set_default_commands(bot)

    # Auto-sync channels from config
    for ch_ref in CONFIG_CHANNELS:
        try:
            chat = await bot.get_chat(parse_chat_id(ch_ref))
            title = chat.title or ch_ref
            link = f"https://t.me/{chat.username}" if chat.username else (chat.invite_link or f"https://t.me/{ch_ref.lstrip('@')}")
            await db.add_channel(
                channel_id=str(chat.id) if not chat.username else f"@{chat.username}",
                title=title,
                invite_link=link,
            )
            logger.info(f"Loaded mandatory channel: {title} ({ch_ref})")
        except Exception as e:
            logger.warning(f"Could not load channel {ch_ref}: {e}")

    logger.info("Starting @Islomovkinobot polling...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped.")
