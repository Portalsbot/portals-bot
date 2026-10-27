# Portals Bot — MVP

## Deploy
1. Create a Neon PostgreSQL database and copy the connection string (SSL enabled).
2. Create a private Telegram repository channel and add the bot as administrator with permission to post.
3. In Render create a Background Worker from this repo. Build: `pip install -r requirements.txt`; start: `python main.py`.
4. Set environment variables: `BOT_TOKEN`, `DATABASE_URL`, `OWNER_ID=8043083450`, `REPO_CHANNEL_ID`, `LINK_TTL_SECONDS=180`, `DELETE_AFTER_SECONDS=600`.
5. After deployment, open the bot and send `/start`, then `/settings`.

## Telegram commands
- `/settings`: menu with channel links, editable text, repository channel, expiry, upload guidance.
- `/setchannels https://t.me/channel`, `/setdirectory https://t.me/directory`, `/setsupport https://t.me/support`. Use `-` to clear.
- `/setrepository -1001234567890`: set private repository channel ID.
- `/setttl 180`: access-link expiry in seconds (30–86400).
- `/upload Collection title`, send items in order, `/finish`, then `/link COLLECTION_ID`.
- `/addadmin USER_ID` (owner only).

## Scope warning
This is a deployable MVP scaffold, not the complete original specification. It does not yet implement F-subscription checks, premium subscriptions/payments, segmented or scheduled broadcasts, external backups, regain-file buttons, or robust abuse controls. The bot can delete only its own sent messages, not files users already downloaded or saved. Test privately before inviting the community.
