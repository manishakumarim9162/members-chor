import os
import sqlite3
import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.functions.channels import InviteToChannelRequest, JoinChannelRequest
from telethon.errors import UserPrivacyRestrictedError, FloodWaitError

# .env file load karein
load_dotenv()

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
SESSION_STRING = os.getenv("STRING_SESSION")
USERBOT_USERNAME = os.getenv("USERBOT_USERNAME")
MY_MAIN_GROUP = int(os.getenv("MY_MAIN_GROUP_ID"))
OWNER_ID = int(os.getenv("OWNER_ID"))

# Dono clients ko initialize karein
bot = TelegramClient('normal_bot', API_ID, API_HASH).start(bot_token=BOT_TOKEN)
userbot = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)

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

# ----------------- NORMAL BOT LOGIC -----------------

# TRIGGER 1: Jab normal bot kisi group me add ho aur admin bane
@bot.on(events.ChatAction)
async def bot_handler(event):
    if event.user_added and event.user_id == (await bot.get_me()).id:
        permissions = await bot.get_permissions(event.chat_id, 'me')
        
        if permissions.is_admin:
            print(f"\n📥 Normal Bot naye group ({event.chat_id}) me admin bana!")
            print(f"🔄 Userbot (@{USERBOT_USERNAME}) ko invite kiya ja raha hai...")
            
            try:
                # Normal bot aapke userbot ko group me invite karega
                await bot(InviteToChannelRequest(event.chat_id, [USERBOT_USERNAME]))
                print(f"✅ Userbot ko group me successfully invite kar diya gaya.")
            except Exception as e:
                print(f"❌ Userbot ko invite karne me galti (Aapka userbot privacy settings se public hona chahiye): {e}")

# Normal Bot Commands
@bot.on(events.NewMessage(pattern='/start'))
async def start_command(event):
    if event.sender_id == OWNER_ID:
        await event.respond("👋 **Boss!** Main aur Userbot dono active hain. Kisi bhi group me mujhe admin banayein.")

# ----------------- USERBOT LOGIC -----------------

# TRIGGER 2: Jab userbot group me kisi naye message ko dekhe
@userbot.on(events.NewMessage)
async def userbot_msg_handler(event):
    # Agar message private chat me hai ya main group me hai toh ignore karein
    if event.is_private or event.chat_id == MY_MAIN_GROUP:
        return
        
    sender = await event.get_sender()
    if not sender or sender.bot:
        return # Bots ko skip karein

    source_group_id = event.chat_id
    current_count = get_today_count(source_group_id)

    # 20 members ki limit check karein
    if current_count >= 20:
        return

    user_id = sender.id
    user_name = sender.first_name

    try:
        group_entity = await userbot.get_entity(source_group_id)
        group_name = group_entity.title
    except Exception:
        group_name = f"Group_{source_group_id}"

    try:
        print(f"⚙️ Active user mila: {user_name} ({user_id}) in [{group_name}]")
        
        # Userbot use aapke main group me add karega
        await userbot(InviteToChannelRequest(MY_MAIN_GROUP, [user_id]))
        
        new_count = current_count + 1
        update_count(source_group_id, group_name, new_count)
        print(f"🎉 SUCCESS: {user_name} ko main group me add kiya! ({new_count}/20)")
        
        # Anti-spam delay taaki userbot safe rahe
        await asyncio.sleep(20)

    except UserPrivacyRestrictedError:
        print(f"❌ PRIVACY SKIP: {user_name} ki settings restricted hain.")
    except FloodWaitError as e:
        print(f"⚠️ LIMIT: Telegram ne temporary block kiya. {e.seconds}s wait...")
        await asyncio.sleep(e.seconds)
    except Exception as e:
        # Agar user pehle se added hai toh database update nahi hoga par loop chalta rahega
        if "USER_ALREADY_PARTICIPANT" in str(e):
            print(f"ℹ️ {user_name} pehle se hi aapke group me hai.")
        else:
            print(f"❌ ERROR adding {user_name}: {e}")

# MAIN ASYNC EXECUTION
async def main():
    # Userbot ko string session se start karein
    await userbot.start()
    print("✅ Userbot successfully logged in via String Session!")
    print("✅ Normal Bot is running...")
    print("🤖 Dual-System setup is ready! Press Ctrl+C to stop.")
    
    # Dono clients ko parallelly run karein
    await asyncio.gather(
        bot.run_until_disconnected(),
        userbot.run_until_disconnected()
    )

if __name__ == '__main__':
    bot.loop.run_until_complete(main())
    
