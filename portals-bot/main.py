import os, asyncio, secrets, logging
from datetime import datetime, timedelta, timezone
import asyncpg
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("portals-bot")

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
OWNER_ID = int(os.getenv("OWNER_ID", "8043083450"))
REPO_CHANNEL_ID = os.getenv("REPO_CHANNEL_ID", "").strip()
DEFAULT_TTL = int(os.getenv("LINK_TTL_SECONDS", "180"))
DELETE_AFTER = int(os.getenv("DELETE_AFTER_SECONDS", "600"))
pool = None
upload_sessions = {}

DEFAULTS = {
    "start_text": "<b>Welcome to Portals Bot</b>\n\nChoose an option below.",
    "about_text": "<b>About</b>\nAnime collection access bot.",
    "help_text": "<b>Help</b>\nOpen a collection link to receive files. Access links expire.",
    "channels_text": "<b>Our Channels</b>\nUse the button below to visit our channels.",
    "channels_url": "",
    "directory_url": "",
    "support_url": "",
    "repository_channel": REPO_CHANNEL_ID,
    "link_ttl_seconds": str(DEFAULT_TTL),
}

async def db_init():
    global pool
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5, command_timeout=30)
    async with pool.acquire() as c:
        await c.execute("""
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS users(user_id BIGINT PRIMARY KEY, first_seen TIMESTAMPTZ DEFAULT now());
        CREATE TABLE IF NOT EXISTS admins(user_id BIGINT PRIMARY KEY, added_by BIGINT NOT NULL);
        CREATE TABLE IF NOT EXISTS collections(id BIGSERIAL PRIMARY KEY, title TEXT NOT NULL, owner_id BIGINT NOT NULL, created_at TIMESTAMPTZ DEFAULT now());
        CREATE TABLE IF NOT EXISTS files(id BIGSERIAL PRIMARY KEY, collection_id BIGINT REFERENCES collections(id) ON DELETE CASCADE, message_id BIGINT NOT NULL, file_name TEXT NOT NULL, position INT NOT NULL);
        CREATE TABLE IF NOT EXISTS access_tokens(token TEXT PRIMARY KEY, collection_id BIGINT REFERENCES collections(id) ON DELETE CASCADE, expires_at TIMESTAMPTZ NOT NULL);
        """)
        for k, v in DEFAULTS.items():
            await c.execute("INSERT INTO settings(key,value) VALUES($1,$2) ON CONFLICT(key) DO NOTHING", k, v)

async def get_setting(key):
    async with pool.acquire() as c:
        row = await c.fetchrow("SELECT value FROM settings WHERE key=$1", key)
    return row["value"] if row else DEFAULTS.get(key, "")

async def put_setting(key, value):
    async with pool.acquire() as c:
        await c.execute("INSERT INTO settings(key,value) VALUES($1,$2) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value", key, value)

async def authorized(uid):
    if uid == OWNER_ID:
        return True
    async with pool.acquire() as c:
        return bool(await c.fetchval("SELECT EXISTS(SELECT 1 FROM admins WHERE user_id=$1)", uid))

def home_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("About", callback_data="page:about"), InlineKeyboardButton("Channels", callback_data="page:channels")],
        [InlineKeyboardButton("Help", callback_data="page:help")]
    ])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    async with pool.acquire() as c:
        await c.execute("INSERT INTO users(user_id) VALUES($1) ON CONFLICT(user_id) DO NOTHING", uid)
    if context.args:
        await deliver(update, context, context.args[0])
        return
    await update.effective_message.reply_text(await get_setting("start_text"), parse_mode="HTML",
                                              reply_markup=home_keyboard(), disable_web_page_preview=True)

async def page(update, context):
    q = update.callback_query
    await q.answer()
    page_name = q.data.split(":", 1)[1]
    if page_name == "home":
        await q.edit_message_text(await get_setting("start_text"), parse_mode="HTML", reply_markup=home_keyboard())
        return
    key = {"about": "about_text", "channels": "channels_text", "help": "help_text"}[page_name]
    buttons = []
    if page_name == "channels":
        url = await get_setting("channels_url")
        if url: buttons.append([InlineKeyboardButton("Open channels", url=url)])
        url = await get_setting("directory_url")
        if url: buttons.append([InlineKeyboardButton("Anime directory", url=url)])
    if page_name == "help":
        url = await get_setting("support_url")
        if url: buttons.append([InlineKeyboardButton("Support", url=url)])
    buttons.append([InlineKeyboardButton("⬅️ Back", callback_data="page:home")])
    await q.edit_message_text(await get_setting(key), parse_mode="HTML",
                              reply_markup=InlineKeyboardMarkup(buttons), disable_web_page_preview=True)

async def settings(update, context):
    if not await authorized(update.effective_user.id):
        await update.effective_message.reply_text("Not authorized.")
        return
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Channel / directory / support links", callback_data="settings:links")],
        [InlineKeyboardButton("Edit bot texts", callback_data="settings:texts")],
        [InlineKeyboardButton("Repository channel", callback_data="settings:repo")],
        [InlineKeyboardButton("Access-link expiry", callback_data="settings:ttl")],
        [InlineKeyboardButton("Upload instructions", callback_data="settings:upload")]
    ])
    await update.effective_message.reply_text("<b>Portals Bot Settings</b>\nChoose a section to see the command to send.",
                                              parse_mode="HTML", reply_markup=kb)

async def settings_callback(update, context):
    q = update.callback_query
    await q.answer()
    if not await authorized(q.from_user.id):
        await q.edit_message_text("Not authorized.")
        return
    section = q.data.split(":", 1)[1]
    messages = {
      "links": "<b>Set links whenever you decide them</b>\n/setchannels https://t.me/yourchannel\n/setdirectory https://t.me/yourdirectory\n/setsupport https://t.me/yourusername\nUse <code>-</code> after a command to clear its link.",
      "texts": "<b>Edit bot pages</b>\n/setstart Your welcome text\n/setabout Your about text\n/sethelp Your help text\n/setchannelstext Text shown on Channels page\nHTML formatting such as <code>&lt;b&gt;bold&lt;/b&gt;</code> is supported.",
      "repo": "Create a private Telegram channel, add this bot as administrator with permission to post, then use:\n<code>/setrepository -1001234567890</code>",
      "ttl": "Set access-link expiry (30–86400 seconds):\n<code>/setttl 180</code> (3 minutes)",
      "upload": "Use <code>/upload Collection title</code>, then send/forward items in the exact order, then <code>/finish</code>. Create an access link using <code>/link COLLECTION_ID</code>."
    }
    await q.edit_message_text(messages[section], parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to settings", callback_data="settings:back")]]))

async def settings_back(update, context):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text("Use /settings to reopen the settings menu.")

async def set_setting_cmd(update, context, key, command):
    if not await authorized(update.effective_user.id):
        await update.effective_message.reply_text("Not authorized.")
        return
    value = update.effective_message.text.partition(" ")[2].strip()
    if not value:
        await update.effective_message.reply_text(f"Usage: /{command} VALUE")
        return
    if value == "-": value = ""
    await put_setting(key, value)
    await update.effective_message.reply_text(f"Saved {command}.")

async def setstart(u,c): await set_setting_cmd(u,c,"start_text","setstart")
async def setabout(u,c): await set_setting_cmd(u,c,"about_text","setabout")
async def sethelp(u,c): await set_setting_cmd(u,c,"help_text","sethelp")
async def setchannelstext(u,c): await set_setting_cmd(u,c,"channels_text","setchannelstext")
async def setchannels(u,c): await set_setting_cmd(u,c,"channels_url","setchannels")
async def setdirectory(u,c): await set_setting_cmd(u,c,"directory_url","setdirectory")
async def setsupport(u,c): await set_setting_cmd(u,c,"support_url","setsupport")
async def setrepository(u,c): await set_setting_cmd(u,c,"repository_channel","setrepository")

async def setttl(update, context):
    if not await authorized(update.effective_user.id):
        await update.effective_message.reply_text("Not authorized.")
        return
    try:
        seconds = int(context.args[0])
        if not 30 <= seconds <= 86400: raise ValueError()
    except (ValueError, IndexError):
        await update.effective_message.reply_text("Usage: /setttl 180 (30–86400 seconds)")
        return
    await put_setting("link_ttl_seconds", str(seconds))
    await update.effective_message.reply_text(f"Access-link expiry set to {seconds} seconds.")

async def upload(update, context):
    if not await authorized(update.effective_user.id):
        await update.effective_message.reply_text("Not authorized.")
        return
    title = " ".join(context.args).strip()
    if not title:
        await update.effective_message.reply_text("Usage: /upload Collection title")
        return
    upload_sessions[update.effective_user.id] = {"title": title, "items": []}
    await update.effective_message.reply_text(f"Upload started: <b>{title}</b>\nSend/forward items in order, then /finish.", parse_mode="HTML")

async def collect(update, context):
    uid = update.effective_user.id
    if uid not in upload_sessions: return
    msg = update.effective_message
    repo = (await get_setting("repository_channel")).strip()
    if not repo:
        await msg.reply_text("Set the private repository channel first: /settings")
        return
    try:
        copied = await context.bot.copy_message(chat_id=int(repo), from_chat_id=msg.chat_id, message_id=msg.message_id)
    except Exception:
        log.exception("Could not copy item to repository")
        await msg.reply_text("Could not save item. Check repository channel ID and bot admin permissions.")
        return
    media = msg.document or msg.video or msg.audio
    name = getattr(media, "file_name", None) if media else None
    name = name or msg.caption or msg.text or f"Item {len(upload_sessions[uid]['items'])+1}"
    upload_sessions[uid]["items"].append((copied.message_id, name[:250]))
    await msg.reply_text(f"Saved item {len(upload_sessions[uid]['items'])}: {name[:90]}")

async def finish(update, context):
    uid = update.effective_user.id
    if not await authorized(uid):
        await update.effective_message.reply_text("Not authorized.")
        return
    session = upload_sessions.get(uid)
    if not session or not session["items"]:
        await update.effective_message.reply_text("No active upload or no items received.")
        return
    async with pool.acquire() as c:
        async with c.transaction():
            cid = await c.fetchval("INSERT INTO collections(title,owner_id) VALUES($1,$2) RETURNING id", session["title"], uid)
            for position, (mid, name) in enumerate(session["items"], 1):
                await c.execute("INSERT INTO files(collection_id,message_id,file_name,position) VALUES($1,$2,$3,$4)", cid, mid, name, position)
    del upload_sessions[uid]
    await update.effective_message.reply_text(f"Collection saved: <b>{session['title']}</b>\nID: <code>{cid}</code>\nCreate link: <code>/link {cid}</code>", parse_mode="HTML")

async def create_link(update, context):
    if not await authorized(update.effective_user.id):
        await update.effective_message.reply_text("Not authorized.")
        return
    try: cid = int(context.args[0])
    except (ValueError, IndexError):
        await update.effective_message.reply_text("Usage: /link COLLECTION_ID")
        return
    async with pool.acquire() as c:
        if not await c.fetchval("SELECT EXISTS(SELECT 1 FROM collections WHERE id=$1)", cid):
            await update.effective_message.reply_text("Collection ID not found.")
            return
        ttl = int(await get_setting("link_ttl_seconds") or DEFAULT_TTL)
        token = secrets.token_urlsafe(12)
        await c.execute("INSERT INTO access_tokens(token,collection_id,expires_at) VALUES($1,$2,$3)",
                        token, cid, datetime.now(timezone.utc) + timedelta(seconds=ttl))
    bot = await context.bot.get_me()
    await update.effective_message.reply_text(f"Link expires in {ttl} seconds:\nhttps://t.me/{bot.username}?start={token}")

async def deliver(update, context, token):
    async with pool.acquire() as c:
        row = await c.fetchrow("SELECT collection_id,expires_at FROM access_tokens WHERE token=$1", token)
        if not row or row["expires_at"] < datetime.now(timezone.utc):
            await update.effective_message.reply_text("This link has expired or is invalid. Request a fresh link from the directory.")
            return
        files = await c.fetch("SELECT message_id,file_name FROM files WHERE collection_id=$1 ORDER BY position", row["collection_id"])
    repo = (await get_setting("repository_channel")).strip()
    if not repo:
        await update.effective_message.reply_text("Repository channel is not configured.")
        return
    for item in files:
        try:
            sent = await context.bot.copy_message(chat_id=update.effective_chat.id, from_chat_id=int(repo), message_id=item["message_id"])
            context.job_queue.run_once(delete_delivered, DELETE_AFTER, data={"chat_id": update.effective_chat.id, "message_id": sent.message_id})
        except Exception:
            log.exception("Delivery error")
            await update.effective_message.reply_text("Delivery failed. Please contact support.")
            break

async def delete_delivered(context):
    data = context.job.data
    try:
        await context.bot.delete_message(chat_id=data["chat_id"], message_id=data["message_id"])
        await context.bot.send_message(chat_id=data["chat_id"], text="The bot's file message was deleted after 10 minutes. This does not delete copies already downloaded or saved.")
    except Exception:
        log.exception("Auto-delete failed")

async def addadmin(update, context):
    if update.effective_user.id != OWNER_ID:
        await update.effective_message.reply_text("Owner only.")
        return
    try: uid = int(context.args[0])
    except (ValueError, IndexError):
        await update.effective_message.reply_text("Usage: /addadmin USER_ID")
        return
    async with pool.acquire() as c:
        await c.execute("INSERT INTO admins(user_id,added_by) VALUES($1,$2) ON CONFLICT(user_id) DO NOTHING", uid, OWNER_ID)
    await update.effective_message.reply_text(f"Admin added: {uid}")

async def commands(update, context):
    await update.effective_message.reply_text(
        "<b>Commands</b>\n/settings — settings menu\n/upload TITLE — start collection\n/finish — save collection\n/link ID — create expiring link\n/addadmin ID — add admin (owner only)\n"
        "/setchannels URL — channel link\n/setdirectory URL — directory link\n/setsupport URL — support link\n/setrepository CHANNEL_ID — private repository\n/setttl SECONDS — expiry\n/setstart TEXT, /setabout TEXT, /sethelp TEXT, /setchannelstext TEXT — edit bot pages.",
        parse_mode="HTML")

async def post_init(app):
    await db_init()
    await app.bot.set_my_commands([
        ("start", "Open bot"), ("help", "Commands and help"), ("settings", "Admin settings"),
        ("upload", "Start collection upload"), ("finish", "Finish collection"), ("link", "Create access link")
    ])

def main():
    if not BOT_TOKEN or not DATABASE_URL:
        raise RuntimeError("Set BOT_TOKEN and DATABASE_URL environment variables.")
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", commands))
    app.add_handler(CommandHandler("commands", commands))
    app.add_handler(CommandHandler("settings", settings))
    app.add_handler(CommandHandler("upload", upload))
    app.add_handler(CommandHandler("finish", finish))
    app.add_handler(CommandHandler("link", create_link))
    app.add_handler(CommandHandler("addadmin", addadmin))
    for cmd, fn in [
        ("setstart", setstart), ("setabout", setabout), ("sethelp", sethelp),
        ("setchannelstext", setchannelstext), ("setchannels", setchannels),
        ("setdirectory", setdirectory), ("setsupport", setsupport),
        ("setrepository", setrepository), ("setttl", setttl)
    ]:
        app.add_handler(CommandHandler(cmd, fn))
    app.add_handler(CallbackQueryHandler(page, pattern=r"^page:"))
    app.add_handler(CallbackQueryHandler(settings_callback, pattern=r"^settings:(?!back$)"))
    app.add_handler(CallbackQueryHandler(settings_back, pattern=r"^settings:back$"))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, collect))
    app.run_polling(drop_pending_updates=False)

if __name__ == "__main__":
    main()
