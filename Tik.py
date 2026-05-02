import telebot
from telebot import types
import requests
import json
import os
import asyncio
import aiohttp
import threading
import concurrent.futures
from bs4 import BeautifulSoup

# ================= CONFIG =================

TOKEN = os.getenv("TOKEN")
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

# ================= PREF =================

def set_user_pref(user_id, mode):
    USER_PREFS[user_id] = mode

def get_user_pref(user_id):
    return USER_PREFS.get(user_id)

# ================= APIs =================

def api_tikwm(url):
    try:
        r = requests.post("https://tikwm.com/api/", data={"url": url}, timeout=10)
        data = r.json()["data"]
        return {
            "video": data["play"],
            "audio": data["music"],
            "title": data["title"]
        }
    except Exception as e:
        print("tikwm error:", e)
        return None

def api_tiklydown(url):
    try:
        r = requests.get(f"https://api.tiklydown.me/api/download?url={url}", timeout=10)
        data = r.json()
        return {
            "video": data["video"]["noWatermark"],
            "audio": data["video"]["audio"],
            "title": data["video"]["title"]
        }
    except Exception as e:
        print("tiklydown error:", e)
        return None

def api_ssstik(url):
    try:
        headers = {"User-Agent": "Mozilla/5.0"}

        r = requests.post(
            "https://ssstik.io/abc?url=dl",
            data={"id": url, "locale": "en"},
            headers=headers,
            timeout=10
        )

        soup = BeautifulSoup(r.text, "html.parser")

        link = soup.find("a", {"class": "without_watermark"})
        if link:
            return {
                "video": link["href"],
                "audio": None,
                "title": "TikTok Video"
            }

    except Exception as e:
        print("ssstik error:", e)

    return None

# ================= GET DATA =================

def get_data(url, retries=2):
    url = url.split("?")[0]

    apis = [api_tikwm, api_tiklydown, api_ssstik]

    for attempt in range(retries):
        print(f"TRY {attempt+1}")

        with concurrent.futures.ThreadPoolExecutor() as executor:
            futures = {
                executor.submit(api, url): api.__name__ for api in apis
            }

            for future in concurrent.futures.as_completed(futures):
                api_name = futures[future]

                try:
                    data = future.result()
                    if data and data.get("video"):
                        print(f"SUCCESS FROM {api_name}")
                        return data

                except Exception as e:
                    print(f"{api_name} error:", e)

        print("Retrying...")

    return None

# ================= ASYNC AUDIO =================

async def fetch(session, url):
    async with session.get(url) as response:
        return await response.read()

async def download_audio(url, path):
    async with aiohttp.ClientSession() as session:
        data = await fetch(session, url)
        with open(path, "wb") as f:
            f.write(data)

def run_async(coro):
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

    text = f"""🛡️ {display} | أهلاً بيك 👋

🎬 بوت تحميل TikTok

━━━━━━━━━━━━━━━

🔥 بدون علامة مائية
📛 اسم الفيديو الحقيقي
💿 استخراج الصوت
🧠 اختيار أسرع سيرفر

━━━━━━━━━━━━━━━
"""

    bot.send_message(message.chat.id, text, reply_markup=main_buttons())

# ================= AUTO =================

@bot.message_handler(func=lambda m: m.text and "tiktok.com" in m.text)
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

# ================= CALLBACK =================

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
        text = f"""📊 إحصائيات البوت

👥 المستخدمين: {len(stats["users"])}
📥 التحميلات: {stats["downloads"]}

🎬 فيديو: {stats["video"]}
🎧 صوت: {stats["audio"]}
"""
        bot.answer_callback_query(call.id, text, show_alert=True)

# ================= VIDEO =================

def process_video(message):
    msg = bot.send_message(message.chat.id, "⚡ جاري التحميل...")

    def task():
        try:
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

                bot.edit_message_text("✅ تم التحميل", message.chat.id, msg.message_id)

                bot.send_message(message.chat.id, "🔁 عايز تحمل تاني؟", reply_markup=main_buttons())

            else:
                bot.edit_message_text("❌ فشل التحميل من كل السيرفرات", message.chat.id, msg.message_id)

        except Exception as e:
            print("ERROR:", e)
            bot.edit_message_text("❌ حصل خطأ", message.chat.id, msg.message_id)

    threading.Thread(target=task).start()

# ================= AUDIO =================

def process_audio(message):
    msg = bot.send_message(message.chat.id, "⚡ جاري التحميل...")

    def task():
        try:
            data = get_data(message.text)

            if data and data.get("audio"):
                title = data["title"]
                safe = "".join(c for c in title if c.isalnum() or c in " _-")[:50]
                file_path = f"{safe}.mp3"

                run_async(download_audio(data["audio"], file_path))

                with open(file_path, "rb") as f:
                    bot.send_audio(message.chat.id, f, caption=f"🎧 {title}", title=title)

                os.remove(file_path)

                stats = load_stats()
                stats["downloads"] += 1
                stats["audio"] += 1
                save_stats(stats)

                bot.edit_message_text("✅ تم التحميل", message.chat.id, msg.message_id)
                bot.send_message(message.chat.id, "🔁 عايز تحمل تاني؟", reply_markup=main_buttons())

            else:
                bot.edit_message_text("❌ الصوت غير متوفر", message.chat.id, msg.message_id)

        except Exception as e:
            print("ERROR:", e)
            bot.edit_message_text("❌ حصل خطأ", message.chat.id, msg.message_id)

    threading.Thread(target=task).start()

# ================= RUN =================

print("🔥 Bot Running...")
bot.infinity_polling()
