import discord
import asyncio
from datetime import datetime, timedelta, timezone
import os  # Import the os module to access environment variables

# Code for the Flask Web Server to keep the service alive
# This runs in a separate thread to not block the Discord bot
from flask import Flask
from threading import Thread

app = Flask('')

@app.route('/')
def home():
    # This route will be pinged by Uptime Robot to keep the service awake
    return "Bot is alive!"

def run_flask_server():
    # Flask server runs on 0.0.0.0 (all interfaces) and port 8080
    # Render.com will expose this port
    app.run(host='0.0.0.0', port=8080)

def start_keep_alive_server():
    # Start the Flask web server in a background thread
    t = Thread(target=run_flask_server)
    t.start()

# Configure Discord Intents for the bot
# Intents specify which events your bot wants to receive from Discord
# discord.Intents.default() provides basic intents
# message_content is needed to read message commands (if any)
# voice_states is crucial for detecting voice channel join/leave events
# members is necessary to access member data (including roles)
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.members = True

client = discord.Client(intents=intents)

# Define the target role name that the bot will check for
TARGET_ROLE_NAME = "VoiceRuntime"

# Dictionary to store voice channel punishment data for each user
# Structure: {user_id: {'disconnect_count': int, 'punish_time': int, 'last_disconnect_date': datetime.date}}
# - disconnect_count: Tracks how many times a user has disconnected from a voice channel today
# - punish_time: The duration (in seconds) the user will be timed out
# - last_disconnect_date: The last date the user disconnected, used for daily resets
user_punishments = {}

# Event: Triggered when the bot is ready and connected to Discord
@client.event
async def on_ready():
    print(f'เข้าสู่ระบบในฐานะ {client.user}')
    print(
        f'บอทพร้อมใช้งานสำหรับระบบลงโทษ Voice Channel สำหรับผู้ใช้ที่มี Role "{TARGET_ROLE_NAME}"!'
    )

# Event: Triggered when a member's voice state changes (join, leave, move channel, mute/unmute)
@client.event
async def on_voice_state_update(member, before, after):
    # Ignore actions by the bot itself to prevent infinite loops
    if member.id == client.user.id:
        return

    # Check if the user has the target role ("VoiceRuntime")
    # If not, the bot will not apply any punishment rules to them
    has_target_role = discord.utils.get(member.roles,
                                          name=TARGET_ROLE_NAME) is not None

    if not has_target_role:
        print(
            f"ผู้ใช้ {member.display_name} ไม่มี Role '{TARGET_ROLE_NAME}', ไม่มีการตรวจสอบ."
        )
        return # Exit the function if the user doesn't have the target role

    # --- Daily Reset System ---
    # Get the current date (using local time for daily reset logic)
    today = datetime.now().date()

    # Iterate through all tracked users and reset their data if a new day has started
    # Using list() to create a copy of keys to safely modify the dictionary during iteration
    for user_id in list(user_punishments.keys()):
        user_data = user_punishments[user_id]
        if user_data['last_disconnect_date'] != today:
            print(f"รีเซ็ตข้อมูลสำหรับผู้ใช้ {user_id} (วันใหม่แล้ว)")
            user_punishments[user_id] = {
                'disconnect_count': 0,
                'punish_time': 0,
                'last_disconnect_date': today
            }

    # --- Detect Voice Channel Disconnection ---
    # Check if the user was in a voice channel before and is no longer in one now
    if before.channel is not None and after.channel is None:
        user_id = member.id
        print(
            f"ผู้ใช้ {member.display_name} ({user_id}) ออกจากช่องเสียง: {before.channel.name} (มี Role '{TARGET_ROLE_NAME}')"
        )

        # Initialize user's punishment data if it's their first disconnection tracked today
        if user_id not in user_punishments:
            user_punishments[user_id] = {
                'disconnect_count': 0,
                'punish_time': 0,
                'last_disconnect_date': today
            }
            print(f"บันทึกข้อมูลผู้ใช้ใหม่ {user_id}")

        user_data = user_punishments[user_id]

        # Increment disconnect count and update the last disconnection date
        user_data['disconnect_count'] += 1
        user_data['last_disconnect_date'] = today

        # Punishment Logic: Base 5 minutes, then multiply by 2 for subsequent disconnects
        # Example:
        #   1st disconnect: 300 seconds (5 minutes)
        #   2nd disconnect: 300 * 2 = 600 seconds (10 minutes)
        #   3rd disconnect: 600 * 4 = 1200 seconds (20 minutes)
        base_punish_seconds = 300 # 5 minutes
        punish_duration = base_punish_seconds * (2 ** (user_data['disconnect_count'] - 1))
        user_data['punish_time'] = punish_duration

        print(
            f"ผู้ใช้ {member.display_name} ออกครั้งที่ {user_data['disconnect_count']} โดนลงโทษ {punish_duration} วินาที"
        )

        try:
            # Calculate the timeout end time using Discord's UTC utility for "aware datetime"
            timeout_until = discord.utils.utcnow() + timedelta(
                seconds=punish_duration)

            # Apply the timeout to the member
            await member.timeout(
                timeout_until,
                reason="ออกจากช่องเสียงบ่อยเกินไปและมี Role VoiceRuntime"
            )

            # --- Notification Message for Public Channel ---
            public_message = (
                f"{member.mention} คุณถูกแบนไม่ให้เข้า Voice Channel และห้องข้อความบางส่วนเป็นเวลา {punish_duration} วินาที "
                f"เนื่องจาก**เข้าออกห้องเสียงบ่อยเกินไป** (ครั้งที่ {user_data['disconnect_count']})\n\n"
                f"เอ็งก็รู้ว่าข้ารักเอ็งที่สุดด" # <-- เพิ่มข้อความนี้
            )

            if before.channel:
                await before.channel.send(public_message)
            else:
                guild_general_channel = discord.utils.get(
                    member.guild.text_channels, name='general')
                if guild_general_channel:
                    await guild_general_channel.send(public_message)

            # --- Attempt to send a Direct Message (DM) to the user ---
            dm_message = (
                f"เรียน {member.display_name},\n\n"
                f"คุณถูกแบนไม่ให้เข้า Voice Channel และห้องข้อความบางส่วนในเซิร์ฟเวอร์ {member.guild.name} "
                f"เป็นเวลา {punish_duration} วินาที เนื่องจากคุณ**เข้าออกห้องเสียงบ่อยเกินไป** "
                f"(นี่คือครั้งที่ {user_data['disconnect_count']} ในวันนี้)\n\n"
                f"โปรดทราบว่าการกระทำนี้เป็นไปตามกฎของเซิร์ฟเวอร์ เพื่อรักษาความสงบเรียบร้อยในห้องเสียงครับ\n\n"
                f"เอ็งก็รู้ว่าข้ารักเอ็งที่สุดด" # <-- เพิ่มข้อความนี้
            )
            try:
                await member.send(dm_message)
                print(f"ส่ง DM แจ้งเตือนไปยังผู้ใช้ {member.display_name} สำเร็จ")
            except discord.Forbidden:
                print(f"ไม่สามารถส่ง DM ไปยังผู้ใช้ {member.display_name} ได้ (อาจปิด DM จากบอท)")
            except Exception as dm_e:
                print(f"เกิดข้อผิดพลาดในการส่ง DM ไปยังผู้ใช้ {member.display_name}: {dm_e}")

        except discord.Forbidden:
            # Handle cases where the bot does not have the necessary permissions for timeout
            print(
                f"บอทไม่มีสิทธิ์ Timeout ผู้ใช้ {member.display_name} ใน {member.guild.name}"
            )
            if before.channel:
                await before.channel.send(
                    f"บอทไม่มีสิทธิ์ Timeout {member.mention} โปรดให้สิทธิ์ `Timeout Members` แก่บอท"
                )
        except Exception as e:
            # Catch any other unexpected errors during the timeout process
            print(
                f"เกิดข้อผิดพลาดในการ Timeout ผู้ใช้ {member.display_name}: {e}"
            )

    # --- Detect Voice Channel Re-entry (while still under punishment) ---
    # This block is mainly for logging/monitoring if a user tries to re-enter
    # Discord's built-in timeout will prevent actual re-entry
    if before.channel is None and after.channel is not None:
        user_id = member.id
        if user_id in user_punishments and user_punishments[user_id][
                'punish_time'] > 0:
            print(
                f"ผู้ใช้ {member.display_name} พยายามเข้าช่องเสียง: {after.channel.name} ขณะที่มีบทลงโทษ"
            )

# Call the keep_alive function to start the Flask web server thread
start_keep_alive_server()

# Run the Discord bot using the token retrieved from environment variables
# The token is stored securely as an environment variable (e.g., in Render.com or Replit Secrets)
client.run(os.environ['DISCORD_BOT_TOKEN'])
