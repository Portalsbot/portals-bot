# Anime Portals — Unified Telegram Bot

Two separate workflows in one bot:

1. **Permanent file links** — the admin sends a photo, document, video, audio, animation, voice message, video note, or sticker to the bot in private chat. The bot stores its Telegram `file_id` and metadata in PostgreSQL and creates a stable deep link. No file-link expiration or auto-delete job is configured.
2. **Expiring channel invites** — register channels with `/addchannel CHANNEL_ID`, then generate a separate expiring invite with `/invite CHANNEL_ID 180`. The bot must be an administrator in that channel and have permission to invite users. Expiry applies only to the Telegram channel invite link.

## Render setup

- Create a **Background Worker** (not a web service) for a polling bot.
- Build command: `pip install -r requirements.txt`
- Start command: `python main.py`
- Runtime: Python 3.12.11 (provided in `.python-version` and `runtime.txt`)
- Environment variables: `BOT_TOKEN`, `DATABASE_URL`, `OWNER_ID`, `BRAND_URL`, `BRAND_NAME`, `INVITE_TTL_SECONDS`.
- `DATABASE_URL` must be a PostgreSQL connection URL reachable from Render. Keep credentials private.

## First-time setup

1. Add all environment variables in Render.
2. Deploy and open the bot. Send `/start`.
3. For file storage, send media to the bot in your private chat as the owner. It returns a permanent deep link.
4. For invite links, add the bot to the target channel as admin with invite-link permission. Run `/addchannel -100...`, then `/invite -100... 180`.

## Branding and attribution

Bot-generated messages use `https://t.me/Anime_portals` as the branding button. The source repositories' in-app branding is not copied into this independent implementation. If incorporating or redistributing upstream source files later, retain their required license and copyright notices; branding changes do not remove those obligations.

## Important limitations

- A Telegram deep link is stable while the bot, its database row, and Telegram file remain available; it is not a promise of perpetual availability.
- Invite expiration is enforced by Telegram at the requested expiry time. Telegram may reject expiry values outside its allowed range.
- This is a focused unified implementation, not a byte-for-byte merge of every advanced feature in the two upstream projects (for example, force-subscription flows, bulk invite generation, and every admin plugin are not included).
