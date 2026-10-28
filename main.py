import os, logging, asyncio, secrets, time
from datetime import datetime, timedelta, timezone
import asyncpg
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

logging.basicConfig(level=logging.INFO)
log = logging.getLogger('anime-portals')
TOKEN = os.environ['BOT_TOKEN']
DATABASE_URL = os.environ['DATABASE_URL']
OWNER_ID = int(os.environ['OWNER_ID'])
BRAND_URL = os.getenv('BRAND_URL', 'https://t.me/Anime_portals')
BRAND_NAME = os.getenv('BRAND_NAME', 'Anime Portals')
DEFAULT_INVITE_TTL = int(os.getenv('INVITE_TTL_SECONDS', '180'))
DB = None

async def init_db():
    global DB
    DB = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5, command_timeout=30)
    async with DB.acquire() as c:
        await c.execute('''CREATE TABLE IF NOT EXISTS stored_files (
            code TEXT PRIMARY KEY, file_id TEXT NOT NULL, file_type TEXT NOT NULL,
            file_name TEXT, caption TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            created_by BIGINT NOT NULL)''')
        await c.execute('''CREATE TABLE IF NOT EXISTS managed_channels (
            chat_id BIGINT PRIMARY KEY, title TEXT, added_at TIMESTAMPTZ NOT NULL DEFAULT NOW())''')

def is_admin(update: Update):
    return bool(update.effective_user and update.effective_user.id == OWNER_ID)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    payload = context.args[0] if context.args else ''
    if payload.startswith('file_'):
        code = payload[5:]
        async with DB.acquire() as c:
            row = await c.fetchrow('SELECT file_id,file_type,file_name,caption FROM stored_files WHERE code=$1', code)
        if not row:
            await update.effective_message.reply_text('Ye file link valid nahi hai ya file record nahi mila.')
            return
        cap = row['caption'] or ''
        # File records are deliberately not time-limited. No auto-delete job is registered.
        try:
            await context.bot.send_document(update.effective_chat.id, row['file_id'], caption=cap, reply_markup=brand_keyboard()) if row['file_type']=='document' else None
            if row['file_type'] != 'document':
                await send_saved_media(context, update.effective_chat.id, row, cap)
        except TelegramError as e:
            log.exception('Could not deliver stored media: %s', e)
            await update.effective_message.reply_text('File send nahi ho payi. Bot ko storage channel/file access check karna hoga.')
        return
    kb = [[InlineKeyboardButton('Anime Portals', url=BRAND_URL)]]
    msg = ('<b>Anime Portals — File Store & Link Share</b>\n\n'
           '• Permanent file/photo/video links: admin ko file bhejein.\n'
           '• Expiring channel invite links: /invite command use karein.\n\n'
           'File links aur channel invite links ka expiry alag hai.')
    if is_admin(update):
        msg += '\n\n<b>Admin:</b> file ko bot ke private chat mein bhejein; bot permanent link bana dega.\n'
        msg += '<code>/addchannel CHANNEL_ID</code> — channel register karein\n'
        msg += '<code>/channels</code> — registered channels dekhein\n'
        msg += '<code>/invite CHANNEL_ID [seconds]</code> — expiring invite button banayein'
    await update.effective_message.reply_text(msg, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb))

def brand_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton('Anime Portals', url=BRAND_URL)]])

async def send_saved_media(context, chat_id, row, caption):
    fid, typ = row['file_id'], row['file_type']
    kb = brand_keyboard()
    if typ == 'photo': await context.bot.send_photo(chat_id, fid, caption=caption, reply_markup=kb)
    elif typ == 'video': await context.bot.send_video(chat_id, fid, caption=caption, reply_markup=kb)
    elif typ == 'animation': await context.bot.send_animation(chat_id, fid, caption=caption, reply_markup=kb)
    elif typ == 'audio': await context.bot.send_audio(chat_id, fid, caption=caption, reply_markup=kb)
    elif typ == 'voice': await context.bot.send_voice(chat_id, fid, caption=caption, reply_markup=kb)
    elif typ == 'video_note': await context.bot.send_video_note(chat_id, fid, reply_markup=kb)
    elif typ == 'sticker': await context.bot.send_sticker(chat_id, fid, reply_markup=kb)
    else: await context.bot.send_document(chat_id, fid, caption=caption, reply_markup=kb)

async def save_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    m = update.effective_message
    typ, fid, fname = None, None, None
    if m.photo: typ, fid = 'photo', m.photo[-1].file_id
    elif m.document: typ, fid, fname = 'document', m.document.file_id, m.document.file_name
    elif m.video: typ, fid, fname = 'video', m.video.file_id, m.video.file_name
    elif m.animation: typ, fid, fname = 'animation', m.animation.file_id, m.animation.file_name
    elif m.audio: typ, fid, fname = 'audio', m.audio.file_id, m.audio.file_name
    elif m.voice: typ, fid = 'voice', m.voice.file_id
    elif m.video_note: typ, fid = 'video_note', m.video_note.file_id
    elif m.sticker: typ, fid = 'sticker', m.sticker.file_id
    if not fid: return
    code = secrets.token_urlsafe(8).replace('-', '').replace('_', '')[:11]
    caption = m.caption or ''
    async with DB.acquire() as c:
        await c.execute('INSERT INTO stored_files(code,file_id,file_type,file_name,caption,created_by) VALUES($1,$2,$3,$4,$5,$6)', code, fid, typ, fname, caption, update.effective_user.id)
    me = await context.bot.get_me()
    url = f'https://t.me/{me.username}?start=file_{code}'
    # Filename appears in a quoted block; the violet styling is Telegram's client-side quote rendering.
    display_name = fname or ('Photo' if typ == 'photo' else typ.title())
    safe_name = display_name.replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')
    text = f'Permanent file link created.\n\n<blockquote>📁 <b>{safe_name}</b></blockquote>\n<code>{url}</code>\n\nFile link expire nahi hoga; channel invite expiry isse independent hai.'
    await m.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Open File', url=url)], [InlineKeyboardButton('Anime Portals', url=BRAND_URL)]] ) )

async def addchannel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    if not context.args:
        await update.effective_message.reply_text('Usage: /addchannel CHANNEL_ID'); return
    try: cid = int(context.args[0])
    except ValueError:
        await update.effective_message.reply_text('Channel ID numeric hona chahiye, jaise -1001234567890.'); return
    try:
        chat = await context.bot.get_chat(cid)
        # Creating invites requires bot admin permission with invite-link rights.
        async with DB.acquire() as c:
            await c.execute('INSERT INTO managed_channels(chat_id,title) VALUES($1,$2) ON CONFLICT(chat_id) DO UPDATE SET title=EXCLUDED.title', cid, chat.title or str(cid))
        await update.effective_message.reply_text(f'Channel saved: {chat.title or cid}\nInvite banane ke liye bot ko channel mein admin aur invite-link permission dein.')
    except TelegramError as e:
        await update.effective_message.reply_text(f'Channel access error: {e}. Bot ko channel mein add karke admin banayein.')

async def channels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    async with DB.acquire() as c: rows = await c.fetch('SELECT chat_id,title FROM managed_channels ORDER BY added_at DESC')
    if not rows: await update.effective_message.reply_text('Abhi koi channel registered nahi. /addchannel CHANNEL_ID'); return
    await update.effective_message.reply_text('\n'.join(f'• {r["title"]} — <code>{r["chat_id"]}</code>' for r in rows), parse_mode=ParseMode.HTML)

async def invite(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    if not context.args:
        await update.effective_message.reply_text('Usage: /invite CHANNEL_ID [expiry_seconds]\nExample: /invite -1001234567890 180'); return
    try:
        cid = int(context.args[0]); ttl = int(context.args[1]) if len(context.args)>1 else DEFAULT_INVITE_TTL
        if ttl < 30 or ttl > 2_419_200: raise ValueError
    except ValueError:
        await update.effective_message.reply_text('Channel ID/expiry invalid. Expiry 30 se 2419200 seconds ke beech rakhein.'); return
    async with DB.acquire() as c:
        row = await c.fetchrow('SELECT title FROM managed_channels WHERE chat_id=$1', cid)
    if not row:
        await update.effective_message.reply_text('Channel register nahi hai. Pehle /addchannel CHANNEL_ID karein.'); return
    try:
        expires = datetime.now(timezone.utc) + timedelta(seconds=ttl)
        link = await context.bot.create_chat_invite_link(chat_id=cid, expire_date=expires, name=f'Anime Portals {ttl}s')
        label = (row['title'] or 'Channel').replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')
        text = (f'<b>Expiring channel invite</b>\n\n<blockquote>🔗 {label}</blockquote>\n'
                f'This invite expires in <b>{ttl} seconds</b>. File links are not affected.')
        await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Join Channel', url=link.invite_link)], [InlineKeyboardButton('Anime Portals', url=BRAND_URL)]]))
    except TelegramError as e:
        await update.effective_message.reply_text(f'Invite create nahi hui: {e}. Bot ka admin/invite permission check karein.')

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text('Admin commands:\n/addchannel CHANNEL_ID\n/channels\n/invite CHANNEL_ID [seconds]\n\nPermanent file link banane ke liye admin bot ko file/photo/video bheje. /start file links kholta hai.')

async def post_init(app: Application):
    await init_db()
    log.info('Database initialized; permanent file store and expiring invite workflows ready')

async def post_shutdown(app: Application):
    if DB: await DB.close()

def main():
    app = Application.builder().token(TOKEN).post_init(post_init).post_shutdown(post_shutdown).build()
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('help', help_cmd))
    app.add_handler(CommandHandler('addchannel', addchannel))
    app.add_handler(CommandHandler('channels', channels))
    app.add_handler(CommandHandler('invite', invite))
    media_filter = filters.PHOTO | filters.Document.ALL | filters.VIDEO | filters.ANIMATION | filters.AUDIO | filters.VOICE | filters.VIDEO_NOTE | filters.Sticker.ALL
    app.add_handler(MessageHandler(media_filter & filters.ChatType.PRIVATE, save_media))
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__': main()
