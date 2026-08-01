import os
import sqlite3
import asyncio
from datetime import datetime
from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.tl.types import ChannelParticipantsAdmins
from telethon.errors import UserPrivacyRestrictedError, FloodWaitError
from apscheduler.schedulers.asyncio import AsyncioScheduler

# Environment variables load karein
load_dotenv()

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
MY_MAIN_GROUP = int(os.getenv("MY_MAIN_GROUP_ID"))
OWNER_ID = int(os.getenv("OWNER_ID"))

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
    print("Daily limits reset successfully!")

def get_all_status():
    cursor.execute("SELECT group_name, count, group_id FROM daily_limits")
    return cursor.fetchall()

# MAIN LOGIC: Members Transfer
async def transfer_members_from_group(source_group_id):
    current_count = get_today_count(source_group_id)
    
    if current_count >= 20:
        print(f"Group {source_group_id} ki aaj ki limit poori ho chuki hai.")
        return

    try:
        entity = await bot.get_entity(source_group_id)
        group_name = entity.title
    except Exception:
        group_name = f"Group_{source_group_id}"

    print(f"[{group_name}] se members nikalna shuru ho raha hai...")
    
    admin_ids = set()
    try:
        async for admin in bot.iter_participants(source_group_id, filter=ChannelParticipantsAdmins):
            admin_ids.add(admin.id)
    except Exception as e:
        print(f"Admins list fetch nahi ho payi: {e}. Safe side ke liye transfer cancel.")
        return

    added_in_this_session = 0
    max_to_add = 20 - current_count

    try:
        async for user in bot.iter_participants(source_group_id):
            if user.bot:
                continue
            
            if user.id in admin_ids:
                continue # Group admins ko skip karein
            
            if added_in_this_session >= max_to_add:
                break

            try:
                await bot.invite_to_channel(MY_MAIN_GROUP, [user.id])
                
                added_in_this_session += 1
                update_count(source_group_id, group_name, current_count + added_in_this_session)
                print(f"[{group_name}] Added: {user.first_name}")
                
                await asyncio.sleep(20)

            except UserPrivacyRestrictedError:
                pass 
            except FloodWaitError as e:
                print(f"Telegram Limit! {e.seconds} seconds ke liye break.")
                await asyncio.sleep(e.seconds)
            except Exception:
                pass

    except Exception as e:
        print(f"Members fetch karne me error: {e}")

# TRIGGER: Naye group me admin bante hi kaam shuru
@bot.on(events.ChatAction)
async def handler(event):
    if event.user_added and event.user_id == (await bot.get_me()).id:
        permissions = await bot.get_permissions(event.chat_id, 'me')
        if permissions.is_admin:
            asyncio.create_task(transfer_members_from_group(event.chat_id))

# COMMAND: /start
@bot.on(events.NewMessage(pattern='/start'))
async def start_command(event):
    sender_id = event.sender_id
    
    # Check karein agar message bhejne wala khud OWNER hai
    if sender_id == OWNER_ID:
        welcome_owner = (
            "👋 **Welcome Back, Boss!** 😎\n\n"
            "Main aapka Member Scraper Bot hoon. Main bilkul sahi chal raha hoon.\n\n"
            "🛠️ **Aapke Commands:**\n"
            "📊 /status - Aaj ki live transfer report dekhne ke liye."
        )
        await event.respond(welcome_owner)
    else:
        # Baaki normal users ke liye message
        welcome_user = (
            "👋 **Hello!**\n\n"
            "Main ek Group Management Helper Bot hoon. Mujhe use karne ke liye aapke paas owner permissions honi chahiye."
        )
        await event.respond(welcome_user)

# COMMAND: /status (Sirf Owner ke liye)
@bot.on(events.NewMessage(pattern='/status'))
async def status_command(event):
    if event.sender_id != OWNER_ID:
        await event.respond("❌ Aap is bot ke **Owner** nahi hain. Yeh command aapke liye nahi hai.")
        return

    rows = get_all_status()
    if not rows:
        await event.respond("📊 **Status Report:**\nAbhi tak kisi bhi group se koi member add nahi kiya gaya hai.")
        return

    report = "📊 **Daily Transfer Status Report:**\n\n"
    total_added_today = 0
    
    for name, count, gid in rows:
        report += f"🔹 **{name}**\n   └ Added Today: `{count}/20`\n"
        total_added_today += count
        
    report += f"\n📈 **Total Members Added Today:** `{total_added_today}`"
    await event.respond(report)

# SCHEDULER: Raat 12 baje limit reset
scheduler = AsyncioScheduler()
scheduler.add_job(reset_daily_limits, 'cron', hour=0, minute=0)
scheduler.start()

print("Bot Running... /start and /status commands ready.")
bot.run_until_disconnected()
      
