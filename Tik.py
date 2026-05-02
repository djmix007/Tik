import telebot
from telebot import types
import requests
import json
import os
import asyncio
import aiohttp
import threading
import concurrent.futures

TOKEN = "8582326537:AAEIqaGuU24vekRPFqZnHSV9mS6CczJu_xw"
bot = telebot.TeleBot(TOKEN)

STATS_FILE = "stats.json"
USER_PREFS = {}

# ================= STATS =================

def load_stats():
    if not os.path.exists(STATS_FILE):
        return {"users": [], "downloads": 0, "video": 0, "audio": 0}
    try:
        with open(STATS_FILE, "r") as f:
            return json.load(f)
    except:
        return {"users": [], "downloads": 0, "video": 0, "audio": 0}

def save_stats(stats):
    with open(STATS_FILE, "w") as f:
        json.dump(stats, f)

def add_user(user_id):
    stats = load_stats()
    if user_id not in stats["users"]:
        stats["users"].append(user_id)
        save_stats(stats)

# ================= USER PREF =================

def set_user_pref(user_id, mode):
    USER_PREFS[user_id] = mode

def get_user_pref(user_id):
    return USER_PREFS.get(user_id)

# ================= APIs =================

def api_tikwm(url):
    try:
        r = requests.post("https://tikwm.com/api/", data={"url": url})
        data = r.json()["data"]
        return {
            "video": data["play"],
            "audio": data["music"],
            "title": data["title"]
        }
    except:
        return None

def api_tiklydown(url):
    try:
        r = requests.get(f"https://api.tiklydown.me/api/download?url={url}")
        data = r.json()
        return {
            "video": data["video"]["noWatermark"],
            "audio": data["video"]["audio"],
            "title": data["video"]["title"]
        }
    except:
        return None

# Parallel APIs
def get_data(url):
    apis = [api_tikwm, api_tiklydown]

    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = [executor.submit(api, url) for api in apis]

        for future in concurrent.futures.as_completed(futures):
            data = future.result()
            if data and data.get("video"):
                return data
    return None

# ================= ASYNC =================

async def fetch(session, url):
    async with session.get(url) as response:
        return await response.read()

async def download_audio_fast(audio_url, file_path):
    async with aiohttp.ClientSession() as session:
        data = await fetch(session, audio_url)
        with open(file_path, "wb") as f:
            f.write(data)

def run_async_task(coro):
    asyncio.run(coro)

# ================= UI =================

def main_buttons():
    markup = types.InlineKeyboardMarkup()
    markup.row(
        types.InlineKeyboardButton("🎬 فيديو", callback_data="video"),
        types.InlineKeyboardButton("🎧 صوت", callback_data="audio")
    )
    markup.row(
        types.InlineKeyboardButton("📊 Stats", callback_data="stats"),
        types.InlineKeyboardButton("🏠 الرئيسية", callback_data="home")
    )
    return markup

# ================= START =================

@bot.message_handler(commands=['start'])
def start(message):
    add_user(message.from_user.id)

    name = message.from_user.first_name
    username = message.from_user.username
    display = f"@{username}" if username else name

    text = f""" {display} | أهلاً بيك 👋

🎬 بوت تحميل TikTok

━━━━━━━━━━━━━━━

🔥 بدون علامة مائية
📛 اسم الفيديو الحقيقي
💿 استخراج الصوت
🧠 ذكاء اختيار السيرفر

━━━━━━━━━━━━━━━
"""

    bot.send_message(message.chat.id, text, reply_markup=main_buttons())

# ================= AUTO DOWNLOAD =================

@bot.message_handler(func=lambda message: message.text and "tiktok.com" in message.text)
def auto_download(message):
    add_user(message.from_user.id)

    pref = get_user_pref(message.from_user.id)

    if pref == "video":
        process_video(message)
    elif pref == "audio":
        process_audio(message)
    else:
        markup = types.InlineKeyboardMarkup()
        markup.row(
            types.InlineKeyboardButton("🎬 فيديو", callback_data="video"),
            types.InlineKeyboardButton("🎧 صوت", callback_data="audio")
        )
        bot.send_message(message.chat.id, "🎯 تختار تحمل إيه؟", reply_markup=markup)

# ================= BUTTONS =================

@bot.callback_query_handler(func=lambda call: True)
def callback(call):

    if call.data == "video":
        set_user_pref(call.from_user.id, "video")
        msg = bot.send_message(call.message.chat.id, "📥 ابعت لينك TikTok")
        bot.register_next_step_handler(msg, process_video)

    elif call.data == "audio":
        set_user_pref(call.from_user.id, "audio")
        msg = bot.send_message(call.message.chat.id, "🎧 ابعت لينك TikTok")
        bot.register_next_step_handler(msg, process_audio)

    elif call.data == "home":
        bot.send_message(call.message.chat.id, "🏠 القائمة الرئيسية", reply_markup=main_buttons())

    elif call.data == "stats":
        stats = load_stats()
        users = len(stats["users"])
        downloads = stats["downloads"]
        video = stats["video"]
        audio = stats["audio"]

        percent_video = (video / downloads * 100) if downloads else 0
        percent_audio = (audio / downloads * 100) if downloads else 0

        text = f"""📊 إحصائيات البوت

👥 المستخدمين: {users}
📥 التحميلات: {downloads}

🎬 فيديو: {video} ({percent_video:.1f}%)
🎧 صوت: {audio} ({percent_audio:.1f}%)
"""
        bot.answer_callback_query(call.id, text, show_alert=True)

# ================= VIDEO =================

def process_video(message):
    bot.send_message(message.chat.id, "⚡ جاري التحميل...")

    def task():
        data = get_data(message.text)

        if data:
            bot.send_video(
                message.chat.id,
                data["video"],
                caption=f"🎬 {data['title']}"
            )

            stats = load_stats()
            stats["downloads"] += 1
            stats["video"] += 1
            save_stats(stats)

            bot.send_message(
                message.chat.id,
                "✅ تم التحميل\n\n🔁 عايز تحمل تاني؟",
                reply_markup=main_buttons()
            )
        else:
            bot.send_message(message.chat.id, "❌ فشل التحميل")

    threading.Thread(target=task).start()

# ================= AUDIO =================

def process_audio(message):
    bot.send_message(message.chat.id, "⚡ جاري التحميل...")

    def task():
        data = get_data(message.text)

        if data:
            title = data["title"]
            safe_name = "".join(c for c in title if c.isalnum() or c in " _-")[:50]
            file_path = f"{safe_name}.mp3"

            run_async_task(download_audio_fast(data["audio"], file_path))

            with open(file_path, "rb") as f:
                bot.send_audio(
                    message.chat.id,
                    f,
                    caption=f"🎧 {title}",
                    title=title
                )

            os.remove(file_path)

            stats = load_stats()
            stats["downloads"] += 1
            stats["audio"] += 1
            save_stats(stats)

            bot.send_message(
                message.chat.id,
                "✅ تم التحميل\n\n🔁 عايز تحمل تاني؟",
                reply_markup=main_buttons()
            )
        else:
            bot.send_message(message.chat.id, "❌ فشل التحميل")

    threading.Thread(target=task).start()

# ================= RUN =================

print("🔥 Bot is running...")
bot.infinity_polling()
