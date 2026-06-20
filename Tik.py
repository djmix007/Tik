import telebot
from telebot import types
import requests
import json
import os
import asyncio
import aiohttp
import threading
import concurrent.futures
import time
from bs4 import BeautifulSoup
import re
from datetime import datetime, timedelta

# ================= CONFIG =================

TOKEN = os.getenv("TOKEN")
if not TOKEN:
    raise ValueError("❌ TOKEN غير موجود! تأكد من إضافته في متغيرات البيئة")

bot = telebot.TeleBot(TOKEN, parse_mode=None)

STATS_FILE = "stats.json"
CACHE_FILE = "cache.json"
USER_PREFS = {}
USER_LIMITS = {}

# ================= STATS =================

def load_stats():
    if not os.path.exists(STATS_FILE):
        return {"users": [], "downloads": 0, "video": 0, "audio": 0, "errors": 0}
    try:
        with open(STATS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {"users": [], "downloads": 0, "video": 0, "audio": 0, "errors": 0}

def save_stats(stats):
    with open(STATS_FILE, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

def add_user(user_id):
    stats = load_stats()
    if user_id not in stats["users"]:
        stats["users"].append(user_id)
        save_stats(stats)

def increment_downloads(type_):
    stats = load_stats()
    stats["downloads"] += 1
    if type_ == "video":
        stats["video"] += 1
    elif type_ == "audio":
        stats["audio"] += 1
    save_stats(stats)

# ================= CACHE =================

def load_cache():
    if not os.path.exists(CACHE_FILE):
        return {}
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}

def save_cache(cache):
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

def get_cache(url):
    cache = load_cache()
    item = cache.get(url)
    
    if not item:
        return None
    
    # expire بعد 24 ساعة
    if time.time() - item.get("time", 0) > 86400:
        return None
    
    return item.get("data")

def set_cache(url, data):
    cache = load_cache()
    cache[url] = {
        "data": data,
        "time": time.time()
    }
    save_cache(cache)

# ================= RATE LIMITING =================

def check_limit(user_id):
    """الحد الأقصى 30 تحميل لكل مستخدم يومياً"""
    today = datetime.now().strftime("%Y-%m-%d")
    key = f"{user_id}_{today}"
    
    if key not in USER_LIMITS:
        USER_LIMITS[key] = {"count": 0, "date": today}
    
    # إذا كان اليوم مختلف، إعادة تعيين العداد
    if USER_LIMITS[key]["date"] != today:
        USER_LIMITS[key] = {"count": 0, "date": today}
    
    if USER_LIMITS[key]["count"] >= 30:
        return False
    
    USER_LIMITS[key]["count"] += 1
    return True

def get_remaining_limit(user_id):
    today = datetime.now().strftime("%Y-%m-%d")
    key = f"{user_id}_{today}"
    
    if key not in USER_LIMITS:
        return 30
    
    if USER_LIMITS[key]["date"] != today:
        return 30
    
    return 30 - USER_LIMITS[key]["count"]

# ================= PREF =================

def set_user_pref(user_id, mode):
    USER_PREFS[str(user_id)] = mode

def get_user_pref(user_id):
    return USER_PREFS.get(str(user_id))

# ================= APIs =================

def api_tikwm(url):
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        r = requests.post("https://tikwm.com/api/", data={"url": url}, headers=headers, timeout=15)
        data = r.json()
        
        if data.get("code") == 0 and data.get("data"):
            video_data = data["data"]
            return {
                "video": video_data.get("play"),
                "audio": video_data.get("music"),
                "title": video_data.get("title", "TikTok Video"),
                "images": video_data.get("images", [])
            }
    except Exception as e:
        print(f"❌ tikwm error: {e}")
    return None

def api_tiklydown(url):
    try:
        r = requests.get(f"https://api.tiklydown.me/api/download?url={url}", timeout=15)
        data = r.json()
        
        if data.get("success") and data.get("video"):
            return {
                "video": data["video"].get("noWatermark"),
                "audio": data["video"].get("audio"),
                "title": data["video"].get("title", "TikTok Video"),
                "images": data.get("images", [])
            }
    except Exception as e:
        print(f"❌ tiklydown error: {e}")
    return None

def api_ssstik(url):
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Content-Type": "application/x-www-form-urlencoded"
        }
        r = requests.post(
            "https://ssstik.io/abc?url=dl",
            data={"id": url, "locale": "en"},
            headers=headers,
            timeout=15
        )
        soup = BeautifulSoup(r.text, "html.parser")
        
        # البحث عن رابط بدون علامة مائية
        link = soup.find("a", {"class": "without_watermark"})
        if link and link.get("href"):
            return {
                "video": link["href"],
                "audio": None,
                "title": "TikTok Video",
                "images": []
            }
    except Exception as e:
        print(f"❌ ssstik error: {e}")
    return None

def api_tikmate(url):
    """API إضافية للنسخ الاحتياطي"""
    try:
        r = requests.get(f"https://api.tikmate.app/api/get?url={url}", timeout=15)
        data = r.json()
        
        if data.get("success") and data.get("url"):
            return {
                "video": data["url"],
                "audio": None,
                "title": data.get("title", "TikTok Video"),
                "images": []
            }
    except Exception as e:
        print(f"❌ tikmate error: {e}")
    return None

# ================= GET DATA =================

def get_data(url, retries=3):
    # تنظيف الرابط
    url = url.split("?")[0]
    if not url.startswith("https://"):
        url = "https://" + url
    
    # 🚀 CACHE FIRST
    cached = get_cache(url)
    if cached:
        print("⚡ FROM CACHE")
        return cached
    
    apis = [api_tikwm, api_tiklydown, api_ssstik, api_tikmate]
    
    for attempt in range(retries):
        print(f"🔄 TRY {attempt+1}/{retries}")
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            futures = {
                executor.submit(api, url): api.__name__ for api in apis
            }
            
            for future in concurrent.futures.as_completed(futures):
                try:
                    data = future.result(timeout=20)
                    if data and data.get("video"):
                        print(f"✅ SUCCESS from {futures[future]}")
                        set_cache(url, data)
                        return data
                except concurrent.futures.TimeoutError:
                    print(f"⏰ Timeout from {futures[future]}")
                except Exception as e:
                    print(f"❌ Error from {futures[future]}: {e}")
        
        if attempt < retries - 1:
            wait_time = 2 ** attempt
            print(f"⏳ Waiting {wait_time}s before retry...")
            time.sleep(wait_time)
    
    print("❌ ALL APIs FAILED")
    return None

# ================= ASYNC AUDIO =================

async def download_audio_async(url, path):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as response:
                if response.status == 200:
                    data = await response.read()
                    with open(path, "wb") as f:
                        f.write(data)
                    return True
                return False
    except Exception as e:
        print(f"❌ Audio download error: {e}")
        return False

def download_audio_sync(url, path):
    try:
        response = requests.get(url, timeout=30)
        if response.status_code == 200:
            with open(path, "wb") as f:
                f.write(response.content)
            return True
        return False
    except Exception as e:
        print(f"❌ Audio download error: {e}")
        return False

# ================= UI =================

def main_buttons():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("🎬 فيديو", callback_data="video"),
        types.InlineKeyboardButton("🎧 صوت", callback_data="audio"),
        types.InlineKeyboardButton("📊 الإحصائيات", callback_data="stats"),
        types.InlineKeyboardButton("❓ المساعدة", callback_data="help"),
        types.InlineKeyboardButton("📝 عن البوت", callback_data="about")
    )
    return markup

def mode_buttons():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("🎬 فيديو", callback_data="video"),
        types.InlineKeyboardButton("🎧 صوت", callback_data="audio")
    )
    return markup

# ================= START =================

@bot.message_handler(commands=['start'])
def start(message):
    user_id = message.from_user.id
    add_user(user_id)
    
    name = message.from_user.first_name or "👤"
    username = message.from_user.username
    display = f"@{username}" if username else name
    
    text = f"""👋 أهلاً بك {display}!

🎬 **بوت تحميل TikTok**
━━━━━━━━━━━━━━━━━━━━
✅ بدون علامة مائية
🎵 استخراج الصوت MP3
⚡ سرعة فائقة مع التخزين المؤقت
🛡️ 3 سيرفرات احتياطية
📊 إحصائيات لحظية

📌 **طريقة الاستخدام:**
• أرسل رابط فيديو تيك توك مباشرة
• أو استخدم الأزرار أدناه

━━━━━━━━━━━━━━━━━━━━
"""
    
    bot.send_message(
        message.chat.id, 
        text, 
        reply_markup=main_buttons(),
        parse_mode="Markdown"
    )

@bot.message_handler(commands=['help'])
def help_command(message):
    text = """❓ **طريقة استخدام البوت**

1️⃣ أرسل رابط فيديو تيك توك مباشرة
2️⃣ اختر نوع التحميل (فيديو/صوت)
3️⃣ انتظر حتى يكتمل التحميل

📌 **الأوامر المتاحة:**
• `/start` - القائمة الرئيسية
• `/help` - هذه الرسالة
• `/stats` - إحصائيات البوت
• `/limit` - عدد التحميلات المتبقية

⚠️ **الحد الأقصى:** 30 تحميل يومياً
"""
    bot.reply_to(message, text, parse_mode="Markdown")

@bot.message_handler(commands=['stats'])
def stats_command(message):
    stats = load_stats()
    text = f"""📊 **إحصائيات البوت**

👥 **المستخدمين:** {len(stats.get("users", []))}
📥 **إجمالي التحميلات:** {stats.get("downloads", 0)}

🎬 **فيديوهات:** {stats.get("video", 0)}
🎧 **صوتيات:** {stats.get("audio", 0)}
❌ **أخطاء:** {stats.get("errors", 0)}

🕐 آخر تحديث: {datetime.now().strftime('%Y-%m-%d %H:%M')}
"""
    bot.reply_to(message, text, parse_mode="Markdown")

@bot.message_handler(commands=['limit'])
def limit_command(message):
    remaining = get_remaining_limit(message.from_user.id)
    text = f"""📊 **التحميلات المتبقية اليوم**

📥 **متبقي:** {remaining} من 30

💡 استخدم التحميلات بحكمة!
"""
    bot.reply_to(message, text, parse_mode="Markdown")

# ================= AUTO =================

@bot.message_handler(func=lambda m: m.text and "tiktok.com" in m.text.lower())
def auto_download(message):
    user_id = message.from_user.id
    add_user(user_id)
    
    # التحقق من الحد اليومي
    if not check_limit(user_id):
        remaining = get_remaining_limit(user_id)
        bot.reply_to(
            message, 
            f"⚠️ **لقد وصلت للحد الأقصى اليومي!**\n\n📊 المتبقي: 0 من 30\n🔄 انتظر حتى الغد لتتمكن من التحميل مجدداً.",
            parse_mode="Markdown"
        )
        return
    
    pref = get_user_pref(user_id)
    
    if pref == "video":
        process_video(message)
    elif pref == "audio":
        process_audio(message)
    else:
        bot.reply_to(
            message, 
            "🎯 **اختر نوع التحميل:**",
            reply_markup=mode_buttons(),
            parse_mode="Markdown"
        )

# ================= CALLBACK =================

@bot.callback_query_handler(func=lambda call: True)
def callback(call):
    try:
        user_id = call.from_user.id
        
        if call.data == "video":
            set_user_pref(user_id, "video")
            bot.answer_callback_query(call.id, "✅ تم اختيار فيديو")
            msg = bot.send_message(
                call.message.chat.id, 
                "📥 **أرسل رابط فيديو تيك توك**",
                parse_mode="Markdown"
            )
            bot.register_next_step_handler(msg, process_video)
            
        elif call.data == "audio":
            set_user_pref(user_id, "audio")
            bot.answer_callback_query(call.id, "✅ تم اختيار صوت")
            msg = bot.send_message(
                call.message.chat.id, 
                "🎧 **أرسل رابط فيديو تيك توك**",
                parse_mode="Markdown"
            )
            bot.register_next_step_handler(msg, process_audio)
            
        elif call.data == "home":
            bot.answer_callback_query(call.id, "🏠 الرئيسية")
            bot.edit_message_text(
                "🏠 **القائمة الرئيسية**",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=main_buttons(),
                parse_mode="Markdown"
            )
            
        elif call.data == "stats":
            stats = load_stats()
            text = f"""📊 **إحصائيات البوت**

👥 **المستخدمين:** {len(stats.get("users", []))}
📥 **التحميلات:** {stats.get("downloads", 0)}

🎬 **فيديو:** {stats.get("video", 0)}
🎧 **صوت:** {stats.get("audio", 0)}
❌ **أخطاء:** {stats.get("errors", 0)}
"""
            bot.answer_callback_query(call.id, text, show_alert=True)
            
        elif call.data == "help":
            bot.answer_callback_query(call.id, "❓ المساعدة")
            text = """❓ **كيفية الاستخدام**

1️⃣ أرسل رابط تيك توك
2️⃣ اختر فيديو أو صوت
3️⃣ انتظر التحميل

📌 **الأوامر:**
/start - الرئيسية
/help - المساعدة
/stats - الإحصائيات
/limit - المتبقي اليوم

⚠️ الحد الأقصى: 30 تحميل يومياً
"""
            bot.edit_message_text(
                text,
                call.message.chat.id,
                call.message.message_id,
                reply_markup=main_buttons(),
                parse_mode="Markdown"
            )
            
        elif call.data == "about":
            bot.answer_callback_query(call.id, "📝 عن البوت")
            text = """📝 **عن البوت**

🎬 **بوت تحميل TikTok**
📌 الإصدار: 2.0

⚙️ **المميزات:**
• 4 سيرفرات احتياطية
• تخزين مؤقت لتسريع التحميل
• استخراج الصوت بصيغة MP3
• إحصائيات لحظية
• حد يومي 30 تحميل

👨‍💻 تم التطوير بواسطة مجتمع مفتوح المصدر
"""
            bot.edit_message_text(
                text,
                call.message.chat.id,
                call.message.message_id,
                reply_markup=main_buttons(),
                parse_mode="Markdown"
            )
            
    except Exception as e:
        print(f"❌ Callback error: {e}")
        bot.answer_callback_query(call.id, "❌ حدث خطأ، حاول مرة أخرى")

# ================= VIDEO =================

def process_video(message):
    if not message.text or "tiktok.com" not in message.text.lower():
        bot.reply_to(message, "❌ **يرجى إرسال رابط تيك توك صحيح**", parse_mode="Markdown")
        return
    
    msg = bot.reply_to(message, "⚡ **جاري تحضير الفيديو...**", parse_mode="Markdown")
    
    def task():
        try:
            data = get_data(message.text)
            
            if data and data.get("video"):
                # إرسال الفيديو
                try:
                    bot.send_video(
                        message.chat.id,
                        data["video"],
                        caption=f"🎬 **{data.get('title', 'TikTok Video')[:200]}**",
                        supports_streaming=True,
                        parse_mode="Markdown"
                    )
                    
                    increment_downloads("video")
                    
                    bot.edit_message_text(
                        "✅ **تم التحميل بنجاح!**",
                        message.chat.id,
                        msg.message_id
                    )
                    
                    remaining = get_remaining_limit(message.from_user.id)
                    bot.send_message(
                        message.chat.id,
                        f"📊 **متبقي اليوم:** {remaining} من 30\n\n🔁 أرسل رابط آخر للتحميل مجدداً!",
                        reply_markup=main_buttons(),
                        parse_mode="Markdown"
                    )
                    
                except Exception as e:
                    print(f"❌ Sending video error: {e}")
                    bot.edit_message_text(
                        "❌ **فشل إرسال الفيديو، حاول مرة أخرى**",
                        message.chat.id,
                        msg.message_id
                    )
                    
            else:
                # تحديث الإحصائيات بالأخطاء
                stats = load_stats()
                stats["errors"] = stats.get("errors", 0) + 1
                save_stats(stats)
                
                bot.edit_message_text(
                    "❌ **فشل التحميل من جميع السيرفرات**\n\n🔄 حاول بعد قليل أو أرسل رابطاً آخر",
                    message.chat.id,
                    msg.message_id
                )
                
        except Exception as e:
            print(f"❌ Process video error: {e}")
            bot.edit_message_text(
                "❌ **حدث خطأ غير متوقع**\n\n🔄 حاول مرة أخرى",
                message.chat.id,
                msg.message_id
            )
    
    threading.Thread(target=task, daemon=True).start()

# ================= AUDIO =================

def process_audio(message):
    if not message.text or "tiktok.com" not in message.text.lower():
        bot.reply_to(message, "❌ **يرجى إرسال رابط تيك توك صحيح**", parse_mode="Markdown")
        return
    
    msg = bot.reply_to(message, "⚡ **جاري تحضير الصوت...**", parse_mode="Markdown")
    
    def task():
        try:
            data = get_data(message.text)
            
            if data and data.get("audio"):
                title = data.get("title", "TikTok Audio")
                # تنظيف اسم الملف
                safe_title = re.sub(r'[<>:"/\\|?*]', '', title)[:50]
                file_path = f"{safe_title}.mp3"
                
                # تحميل الصوت
                try:
                    success = download_audio_sync(data["audio"], file_path)
                    
                    if success and os.path.exists(file_path):
                        with open(file_path, "rb") as f:
                            bot.send_audio(
                                message.chat.id,
                                f,
                                caption=f"🎧 **{title[:200]}**",
                                title=title,
                                parse_mode="Markdown"
                            )
                        
                        os.remove(file_path)
                        
                        increment_downloads("audio")
                        
                        bot.edit_message_text(
                            "✅ **تم التحميل بنجاح!**",
                            message.chat.id,
                            msg.message_id
                        )
                        
                        remaining = get_remaining_limit(message.from_user.id)
                        bot.send_message(
                            message.chat.id,
                            f"📊 **متبقي اليوم:** {remaining} من 30\n\n🔁 أرسل رابط آخر للتحميل مجدداً!",
                            reply_markup=main_buttons(),
                            parse_mode="Markdown"
                        )
                    else:
                        raise Exception("فشل تحميل الصوت")
                        
                except Exception as e:
                    print(f"❌ Audio download/send error: {e}")
                    bot.edit_message_text(
                        "❌ **فشل تحميل الصوت**\n\n🔄 حاول مرة أخرى",
                        message.chat.id,
                        msg.message_id
                    )
                    
            else:
                # تحديث الإحصائيات بالأخطاء
                stats = load_stats()
                stats["errors"] = stats.get("errors", 0) + 1
                save_stats(stats)
                
                bot.edit_message_text(
                    "❌ **الصوت غير متوفر لهذا الفيديو**\n\n🔄 حاول فيديو آخر",
                    message.chat.id,
                    msg.message_id
                )
                
        except Exception as e:
            print(f"❌ Process audio error: {e}")
            bot.edit_message_text(
                "❌ **حدث خطأ غير متوقع**\n\n🔄 حاول مرة أخرى",
                message.chat.id,
                msg.message_id
            )
    
    threading.Thread(target=task, daemon=True).start()

# ================= ERROR HANDLING =================

@bot.message_handler(func=lambda m: True)
def handle_unknown(message):
    if "tiktok.com" not in message.text.lower():
        bot.reply_to(
            message,
            "❌ **يرجى إرسال رابط تيك توك فقط**\n\nأو استخدم الأزرار للبدء",
            reply_markup=main_buttons(),
            parse_mode="Markdown"
        )

# ================= RUN =================

if __name__ == "__main__":
    print("🔥 TikTok Bot is Starting...")
    print(f"📊 Bot Token: {TOKEN[:5]}...{TOKEN[-5:]}")
    print("🔄 Starting infinity polling...")
    
    try:
        bot.infinity_polling(timeout=30, long_polling_timeout=30)
    except Exception as e:
        print(f"❌ Bot crashed: {e}")
        time.sleep(5)
        # إعادة التشغيل التلقائي
        print("🔄 Restarting...")
        os.execv(__file__, sys.argv)
