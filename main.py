import os
import sqlite3
import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.tl.types import ChannelParticipantsAdmins
# NAYA IMPORT: Members add karne ke liye zaroori raw function
from telethon.tl.functions.channels import InviteToChannelRequest
from telethon.errors import UserPrivacyRestrictedError, FloodWaitError
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# .env file load karein
load_dotenv()

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
MY_MAIN_GROUP = int(os.getenv("MY_MAIN_GROUP_ID"))
OWNER_ID = int(os.getenv("OWNER_ID"))

# Duplicate trigger se bachne ke liye set
processing_groups = set()

# Telethon Bot Client Setup
bot = TelegramClient('daily_member_mover', API_ID, API_HASH).start(bot_token=BOT_TOKEN)

# DATABASE SETUP
conn = sqlite3.connect('bot_stats.db')
cursor = conn.cursor()
cursor.execute('''
    CREATE TABLE IF NOT EXISTS daily_limits (
        group_id INTEGER PRIMARY KEY,
        group_name TEXT,
        count INTEGER DEFAULT 0
    )
''')
conn.commit()

def get_today_count(group_id):
    cursor.execute("SELECT count FROM daily_limits WHERE group_id = ?", (group_id,))
    row = cursor.fetchone()
    return row if row else 0

def update_count(group_id, group_name, new_count):
    cursor.execute("INSERT OR REPLACE INTO daily_limits (group_id, group_name, count) VALUES (?, ?, ?)", (group_id, group_name, new_count))
    conn.commit()

def reset_daily_limits():
    cursor.execute("UPDATE daily_limits SET count = 0")
    conn.commit()
    print("Daily limits reset successfully for Indian Time Zone!")

def get_all_status():
    cursor.execute("SELECT group_name, count, group_id FROM daily_limits")
    return cursor.fetchall()

# MAIN LOGIC: Members Transfer Function
async def transfer_members_from_group(source_group_id):
    current_count = get_today_count(source_group_id)
    
    if current_count >= 20:
        print(f"⚠️ Group {source_group_id} ki aaj ki limit poori ho chuki hai.")
        return

    try:
        entity = await bot.get_entity(source_group_id)
        group_name = entity.title
    except Exception:
        group_name = f"Group_{source_group_id}"

    print(f"🔄 [{group_name}] se members nikalna shuru ho raha hai...")
    
    admin_ids = set()
    try:
        async for admin in bot.iter_participants(source_group_id, filter=ChannelParticipantsAdmins):
            admin_ids.add(admin.id)
        print(f"ℹ️ Total {len(admin_ids)} admins/owner mile. Inhe skip kiya jayega.")
    except Exception as e:
        print(f"❌ Admins list fetch nahi ho payi: {e}. Safe side ke liye transfer cancel.")
        return

    added_in_this_session = 0
    max_to_add = 20 - current_count

    try:
        async for user in bot.iter_participants(source_group_id):
            if user.bot:
                continue
            
            if user.id in admin_ids:
                print(f"⏭️ Skipped Admin/Owner: {user.first_name}")
                continue
            
            if added_in_this_session >= max_to_add:
                print(f"✅ [{group_name}] Aaj ke liye 20 members ki limit poori ho gayi!")
                break

            try:
                print(f"⚙️ Adding user: {user.first_name} ({user.id})...")
                
                # --- FIXED METHOD HERE ---
                # Telethon me members add karne ka sahi tareeqa yeh hai:
                await bot(InviteToChannelRequest(MY_MAIN_GROUP, [user.id]))
                # -------------------------
                
                added_in_this_session += 1
                update_count(source_group_id, group_name, current_count + added_in_this_session)
                print(f"🎉 SUCCESS: [{group_name}] Added {user.first_name} ({current_count + added_in_this_session}/20)")
                
                # Speed control delay (15 seconds)
                await asyncio.sleep(15)

            except UserPrivacyRestrictedError:
                print(f"❌ PRIVACY SKIP: {user.first_name} ko add nahi kar sakte (Privacy Settings Restricted).")
                await asyncio.sleep(2)
            except FloodWaitError as e:
                print(f"⚠️ TELEGRAM LIMIT: {e.seconds} seconds ke liye bot block hua. Waiting...")
                await asyncio.sleep(e.seconds)
            except Exception as e:
                print(f"❌ ERROR adding {user.first_name}: {e}")
                await asyncio.sleep(2)

    except Exception as e:
        print(f"❌ Members fetch karne me bada error: {e}")

# TRIGGER: Naye group me admin bante hi kaam shuru
@bot.on(events.ChatAction)
async def handler(event):
    if event.user_added and event.user_id == (await bot.get_me()).id:
        if event.chat_id in processing_groups:
            return
            
        permissions = await bot.get_permissions(event.chat_id, 'me')
        if permissions.is_admin:
            print(f"\n📥 Bot ko naye group ({event.chat_id}) me admin banaya gaya!")
            processing_groups.add(event.chat_id)
            try:
                await transfer_members_from_group(event.chat_id)
            finally:
                processing_groups.remove(event.chat_id)

# COMMAND: /start
@bot.on(events.NewMessage(pattern='/start'))
async def start_command(event):
    if event.sender_id == OWNER_ID:
        await event.respond("👋 **Welcome Back, Boss!** 😎\n\nMain active hoon.\n\n📊 /status - Live report.")
    else:
        await event.respond("👋 Hello! Main ek helper bot hoon.")

# COMMAND: /status
@bot.on(events.NewMessage(pattern='/status'))
async def status_command(event):
    if event.sender_id != OWNER_ID:
        await event.respond("❌ Only for owner.")
        return

    rows = get_all_status()
    if not rows:
        await event.respond("📊 Abhi tak koi member transfer nahi hua hai.")
        return

    report = "📊 **Daily Transfer Status Report (IST):**\n\n"
    total_added_today = 0
    for name, count, gid in rows:
        report += f"🔹 **{name}**\n   └ Added Today: `{count}/20`\n"
        total_added_today += count
    report += f"\n📈 **Total Members Added Today:** `{total_added_today}`"
    await event.respond(report)

# MAIN ASYNC WRAPPER
async def main():
    indian_tz = ZoneInfo("Asia/Kolkata")
    scheduler = AsyncIOScheduler(timezone=indian_tz)
    scheduler.add_job(reset_daily_limits, 'cron', hour=0, minute=0)
    scheduler.start()
    print("Bot safely running under Indian Time Zone... Press Ctrl+C to stop.")
    await bot.run_until_disconnected()

if __name__ == '__main__':
    bot.loop.run_until_complete(main())
        
