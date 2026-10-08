import asyncio
import logging
import sys
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from bot.config import BOT_TOKEN
from bot.database import db
from bot.handlers import user, admin, subscription

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("IslomovKinoBot")


async def set_default_commands(bot: Bot):
    """Sets standard menu commands in Telegram UI."""
    commands = [
        BotCommand(command="start", description="Botni qayta ishga tushirish"),
        BotCommand(command="admin", description="Admin panel (faqat adminlar uchun)"),
    ]
    await bot.set_my_commands(commands)


async def start_healthcheck_server():
    """Starts a minimal web server if PORT is defined (required by platforms like Render/Koyeb)."""
    import os
    from aiohttp import web

    port_env = os.getenv("PORT")
    if not port_env:
        return

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
    logger.info(f"Health-check web server started on port {port}")


async def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN is not configured! Check your .env file.")
        sys.exit(1)

    # Start optional cloud healthcheck web server if PORT is provided
    await start_healthcheck_server()

    # Initialize SQLite Database tables
    logger.info("Initializing database...")
    await db.init_db()

    # Create Bot & Dispatcher
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())

    # Include routers
    # Note: admin and subscription routers must be included before user.router
    dp.include_router(admin.router)
    dp.include_router(subscription.router)
    dp.include_router(user.router)

    # Set Telegram commands menu
    await set_default_commands(bot)

    # Auto-sync mandatory channels from .env (CONFIG_CHANNELS)
    from bot.config import CONFIG_CHANNELS
    for ch_ref in CONFIG_CHANNELS:
        try:
            chat = await bot.get_chat(ch_ref)
            title = chat.title or ch_ref
            link = f"https://t.me/{chat.username}" if chat.username else (chat.invite_link or f"https://t.me/{ch_ref.lstrip('@')}")
            await db.add_channel(
                channel_id=str(chat.id) if not chat.username else f"@{chat.username}",
                title=title,
                invite_link=link,
            )
            logger.info(f"Synchronized mandatory channel from config: {title} ({ch_ref})")
        except Exception as e:
            logger.warning(f"Could not sync channel '{ch_ref}' from config: {e}")

    # Delete any pending webhook updates and start polling
    logger.info("Starting @Islomovkinobot...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped.")
