import os
from flask import Flask
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
import psycopg2
from psycopg2.pool import ThreadedConnectionPool
import threading
import time
import random
import string
from datetime import datetime

# ================= 0. MASTER MAGIC COLOR FIX =================
# Ye Telegram ke naye API rules ke hisaab se khaali style error ko rokega
original_to_dict = InlineKeyboardButton.to_dict
def custom_to_dict(self):
    d = original_to_dict(self)
    style_val = getattr(self, 'style', None)
    if style_val is not None:
        d['style'] = str(style_val)
    elif 'style' in d:
        del d['style']
    return d
InlineKeyboardButton.to_dict = custom_to_dict

# ================= 1. TOKENS & CONFIG =================
TOKEN = '8609194789:AAFeNSlJKOsyfXxR8mgULSl902O9qpnCumU'

# Aapka Supabase Link (Makkhan Database)
DATABASE_URL = "postgresql://postgres.jhhmwbivhohvcicyuxqe:mQcGVnP7gMFHQjYE@aws-1-ap-southeast-1.pooler.supabase.com:6543/postgres?sslmode=require"

ADMIN_ID = 1484173564
APPROVAL_CHANNEL = "@ValiModes_key" 

# High-Speed Threads
bot = telebot.TeleBot(TOKEN, parse_mode='HTML', num_threads=10)

try:
    bot.remove_webhook()
    time.sleep(1)
except: pass

# ================= SAFE ANSWER SHIELD =================
def safe_answer(call):
    try: bot.answer_callback_query(call.id)
    except: pass

# ================= 2. POSTGRESQL CLOUD DATABASE SETUP =================
try:
    db_pool = ThreadedConnectionPool(1, 10, DATABASE_URL)
except Exception as e:
    print("DB Connection Error:", e)

def get_db(): return db_pool.getconn()
def release_db(conn):
    if conn: db_pool.putconn(conn)

def init_db():
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS v_channels (channel_id TEXT PRIMARY KEY, link TEXT, style TEXT DEFAULT 'primary')''')
        c.execute('''CREATE TABLE IF NOT EXISTS v_join_reqs (user_id BIGINT, channel_id TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS v_users (user_id BIGINT PRIMARY KEY, username TEXT, join_date TEXT, coins INTEGER DEFAULT 0, is_banned INTEGER DEFAULT 0)''')
        c.execute('''CREATE TABLE IF NOT EXISTS v_pending_refs (user_id BIGINT PRIMARY KEY, referrer_id BIGINT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS v_completed_refs (user_id BIGINT PRIMARY KEY, referrer_id BIGINT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS v_vip_keys (key_code TEXT PRIMARY KEY, duration INTEGER, status TEXT DEFAULT 'UNUSED', used_by BIGINT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS v_settings (name TEXT PRIMARY KEY, value TEXT)''')
        
        # Insert default settings
        c.execute("INSERT INTO v_settings (name, value) VALUES ('key_link', 'https://www.mediafire.com/file/if3uvvwjbj87lo2/DRIPCLIENT_v6.2_GLOBAL_AP.apks/file') ON CONFLICT (name) DO NOTHING")
        conn.commit()
    finally: release_db(conn)

init_db()

# ================= SECURITY / ANTI-SPAM =================
user_last_msg = {}
temp_channel_data = {} 

def flood_check(user_id):
    now = time.time()
    if user_id in user_last_msg and now - user_last_msg[user_id] < 1.0: return True
    user_last_msg[user_id] = now
    return False

def is_user_banned(user_id):
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute("SELECT is_banned FROM v_users WHERE user_id=%s", (user_id,))
        res = c.fetchone()
        return res and res[0] == 1
    finally: release_db(conn)

# ================= 💰 ADMIN ADD COINS =================
@bot.message_handler(commands=['addcoins'])
def add_coins(message):
    if message.chat.id != ADMIN_ID: return
    try:
        parts = message.text.split()
        if len(parts) != 3:
            bot.reply_to(message, "❌ Format: <code>/addcoins USER_ID COINS</code>")
            return
        target_user = int(parts[1])
        amount = int(parts[2])
        
        conn = get_db()
        try:
            c = conn.cursor()
            c.execute("SELECT * FROM v_users WHERE user_id=%s", (target_user,))
            if not c.fetchone():
                return bot.reply_to(message, "❌ User not found in database.")
                
            c.execute("UPDATE v_users SET coins = coins + %s WHERE user_id=%s", (amount, target_user))
            conn.commit()
        finally: release_db(conn)
        
        bot.reply_to(message, f"✅ <b>{amount} Coins</b> added to {target_user}.")
        try: bot.send_message(target_user, f"🎁 Admin ne aapko <b>{amount} Coins</b> bheje hain!")
        except: pass
    except ValueError: bot.reply_to(message, "❌ Numbers only!")

# ================= 🔗 LINK CHANGER =================
@bot.message_handler(commands=['change'])
def change_link(message):
    if message.chat.id != ADMIN_ID: return
    try:
        new_link = message.text.replace('/change', '').strip()
        if new_link == "": return bot.reply_to(message, "❌ Link cannot be empty!")
        
        conn = get_db()
        try:
            c = conn.cursor()
            c.execute("UPDATE v_settings SET value=%s WHERE name='key_link'", (new_link,))
            conn.commit()
        finally: release_db(conn)
        bot.reply_to(message, f"✅ <b>Link Updated!</b>\nNew link for keys:\n{new_link}")
    except: bot.reply_to(message, "❌ Format: <code>/change [LINK]</code>")

# ================= ADMIN PANEL =================
@bot.message_handler(commands=['admin'])
def admin_panel(message):
    if message.chat.id != ADMIN_ID: return 
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(InlineKeyboardButton("➕ Add Channel", callback_data="add_channel", **{'style': 'primary'}),
               InlineKeyboardButton("➖ Remove Channel", callback_data="remove_channel", **{'style': 'danger'}))
    markup.add(InlineKeyboardButton("📋 View Added Channels", callback_data="view_channels", **{'style': 'success'}))
    markup.add(InlineKeyboardButton("📊 Stats & Users", callback_data="adm_stats", **{'style': 'primary'}),
               InlineKeyboardButton("📢 Broadcast", callback_data="adm_broadcast", **{'style': 'success'}))
    markup.add(InlineKeyboardButton("🚫 Ban User", callback_data="adm_ban", **{'style': 'danger'}),
               InlineKeyboardButton("✅ Unban User", callback_data="adm_unban", **{'style': 'primary'})) 
    markup.add(InlineKeyboardButton("🔑 Gen 1-Day VIP", callback_data="adm_key1", **{'style': 'success'}),
               InlineKeyboardButton("🔑 Gen 7-Day VIP", callback_data="adm_key7", **{'style': 'success'}))
    bot.send_message(message.chat.id, "👨‍💻 <b>Admin Panel</b>", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data in ["add_channel", "remove_channel", "view_channels"] or call.data.startswith("adm_") or call.data.startswith("style_"))
def admin_callbacks(call):
    if call.message.chat.id != ADMIN_ID: return
    safe_answer(call)

    # 🎨 ADMIN SE COLOR POOCHNE KE BAAD SAVE KARNE WALA LOGIC
    if call.data.startswith("style_"):
        style = call.data.split("_")[1]
        data = temp_channel_data.get(call.message.chat.id)
        if data:
            conn = get_db()
            try:
                c = conn.cursor()
                c.execute("INSERT INTO v_channels (channel_id, link, style) VALUES (%s, %s, %s) ON CONFLICT (channel_id) DO UPDATE SET link=EXCLUDED.link, style=EXCLUDED.style", (data['ch_id'], data['link'], style))
                conn.commit()
            finally: release_db(conn)
            bot.edit_message_text(f"✅ Channel <code>{data['ch_id']}</code> successfully add ho gaya!\n🎨 Button Color Saved as: {style.upper()}", chat_id=call.message.chat.id, message_id=call.message.message_id)
            del temp_channel_data[call.message.chat.id]
        return

    if call.data == "add_channel":
        msg = bot.send_message(call.message.chat.id, "🤖 Pehle bot ko channel me Admin banao!\n\nPhir Channel ID send karo:")
        bot.register_next_step_handler(msg, process_add_channel)
        
    elif call.data == "view_channels":
        conn = get_db()
        try:
            c = conn.cursor()
            c.execute("SELECT channel_id, link, style FROM v_channels")
            channels = c.fetchall()
        finally: release_db(conn)
        
        if not channels: return bot.send_message(call.message.chat.id, "❌ No channels added.")
        text = "📋 <b>Added Channels:</b>\n\n"
        for ch in channels:
            style = ch[2] if ch[2] else 'primary'
            text += f"ID: <code>{ch[0]}</code>\n🎨 Color: {style.upper()}\nLink: {ch[1]}\n\n"
        bot.send_message(call.message.chat.id, text, disable_web_page_preview=True)
        
    elif call.data == "remove_channel":
        msg = bot.send_message(call.message.chat.id, "🗑️ Channel ID bhejo remove karne ke liye:")
        bot.register_next_step_handler(msg, process_remove_channel)
        
    elif call.data == "adm_stats":
        conn = get_db()
        try:
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM v_users")
            tot = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM v_users WHERE is_banned=1")
            ban = c.fetchone()[0]
        finally: release_db(conn)
        bot.send_message(call.message.chat.id, f"📊 <b>BOT STATS</b>\n\n👥 Total Users: {tot}\n🟢 Active: {tot-ban}\n🔴 Banned: {ban}")
        
    elif call.data == "adm_broadcast":
        msg = bot.send_message(call.message.chat.id, "📢 Broadcast message bhejo:")
        bot.register_next_step_handler(msg, process_broadcast)
    elif call.data == "adm_ban":
        msg = bot.send_message(call.message.chat.id, "🚫 User ID to BAN:")
        bot.register_next_step_handler(msg, lambda m: toggle_ban(m, 1))
    elif call.data == "adm_unban": 
        msg = bot.send_message(call.message.chat.id, "✅ User ID to UNBAN:")
        bot.register_next_step_handler(msg, lambda m: toggle_ban(m, 0))
    elif call.data in ["adm_key1", "adm_key7"]:
        days = 1 if call.data == "adm_key1" else 7
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=10))
        conn = get_db()
        try:
            c = conn.cursor()
            c.execute("INSERT INTO v_vip_keys (key_code, duration) VALUES (%s, %s)", (code, days))
            conn.commit()
        finally: release_db(conn)
        bot.send_message(call.message.chat.id, f"✅ <b>{days}-Day VIP Key:</b>\n<code>{code}</code>")

def process_add_channel(message):
    ch_id = message.text.strip()
    try:
        bot_member = bot.get_chat_member(ch_id, bot.get_me().id)
        if bot_member.status not in ['administrator', 'creator']:
            return bot.send_message(message.chat.id, "❌ Bot is channel me Admin nahi hai!")
        try: invite_link = bot.create_chat_invite_link(ch_id, creates_join_request=True).invite_link
        except:
            try: invite_link = bot.export_chat_invite_link(ch_id)
            except: return bot.send_message(ADMIN_ID, "❌ *Error:* Invite link permission nahi hai.", parse_mode="Markdown")
        
        temp_channel_data[message.chat.id] = {'ch_id': ch_id, 'link': invite_link}
        
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            InlineKeyboardButton("🔵 Blue (Primary)", callback_data="style_primary", **{'style': 'primary'}),
            InlineKeyboardButton("🟢 Green (Success)", callback_data="style_success", **{'style': 'success'}),
            InlineKeyboardButton("🔴 Red (Danger)", callback_data="style_danger", **{'style': 'danger'}),
            InlineKeyboardButton("⚪ Normal", callback_data="style_normal")
        )
        bot.send_message(message.chat.id, "🎨 <b>Is Channel ke Button ka Color kya rakhna hai?</b>\nNiche diye gaye color options mein se choose karein:", reply_markup=markup)
    except Exception as e: bot.send_message(message.chat.id, f"❌ Error: {e}")

def process_remove_channel(message):
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute("DELETE FROM v_channels WHERE channel_id=%s", (message.text.strip(),))
        conn.commit()
    finally: release_db(conn)
    bot.send_message(message.chat.id, "✅ Channel removed!")

def process_broadcast(message):
    bot.send_message(message.chat.id, "⏳ Broadcasting started...")
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute("SELECT user_id FROM v_users WHERE is_banned=0")
        users = c.fetchall()
    finally: release_db(conn)
    
    sent, failed = 0, 0
    for u in users:
        try:
            bot.copy_message(u[0], message.chat.id, message.message_id)
            sent += 1
            time.sleep(0.05)
        except: failed += 1
    bot.send_message(message.chat.id, f"✅ <b>Broadcast Done!</b>\nSuccess: {sent} | Failed: {failed}")

def toggle_ban(message, status):
    try:
        uid = int(message.text.strip())
        conn = get_db()
        try:
            c = conn.cursor()
            c.execute("UPDATE v_users SET is_banned=%s WHERE user_id=%s", (status, uid))
            conn.commit()
        finally: release_db(conn)
        bot.reply_to(message, f"✅ Done!")
    except: bot.reply_to(message, "❌ Invalid ID.")


# ================= JOIN REQUEST & FORCE SUB =================
@bot.chat_join_request_handler()
def handle_join_request(message: telebot.types.ChatJoinRequest):
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute("INSERT INTO v_join_reqs (user_id, channel_id) VALUES (%s, %s)", (message.from_user.id, str(message.chat.id)))
        conn.commit()
    finally: release_db(conn)

@bot.message_handler(commands=['start'])
def start_cmd(message):
    uid = message.from_user.id
    if flood_check(uid) or is_user_banned(uid): return

    conn = get_db()
    try:
        c = conn.cursor()
        c.execute("SELECT * FROM v_users WHERE user_id=%s", (uid,))
        if not c.fetchone():
            date = datetime.now().strftime("%Y-%m-%d")
            c.execute("INSERT INTO v_users (user_id, username, join_date) VALUES (%s, %s, %s)", (uid, message.from_user.username or "Unknown", date))
            
            args = message.text.split()
            if len(args) > 1 and args[1].isdigit():
                ref_id = int(args[1])
                if ref_id != uid:
                    c.execute("SELECT * FROM v_completed_refs WHERE user_id=%s", (uid,))
                    if not c.fetchone():
                        c.execute("UPDATE v_users SET coins = coins + 2 WHERE user_id=%s", (ref_id,))
                        c.execute("INSERT INTO v_completed_refs (user_id, referrer_id) VALUES (%s, %s)", (uid, ref_id))
                        try: bot.send_message(ref_id, "🎉 <b>Congrats!</b>\nKisi ne aapke link se bot start kiya hai. <b>+2 Coins</b> Added!")
                        except: pass
            conn.commit()
    finally: release_db(conn)
    send_force_sub(message.chat.id, uid)

def check_user_status(user_id):
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute("SELECT channel_id FROM v_channels")
        channels = c.fetchall()
        if not channels: return True 
        for ch in channels:
            joined = False
            try:
                if bot.get_chat_member(ch[0], user_id).status in ['member', 'administrator', 'creator']: joined = True
            except: pass
            if not joined:
                c.execute("SELECT * FROM v_join_reqs WHERE user_id=%s AND channel_id=%s", (user_id, ch[0]))
                if not c.fetchone(): return False 
        return True
    finally: release_db(conn)

def send_force_sub(chat_id, user_id):
    if check_user_status(user_id):
        return send_main_menu(chat_id)
        
    markup = InlineKeyboardMarkup()
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute("SELECT link, style FROM v_channels")
        channels = c.fetchall()
    finally: release_db(conn)
    
    # 🚀 Yahan har line me 3 buttons aayenge aur wahi color hoga jo admin ne add karte time choose kiya tha!
    row = []
    for i, ch in enumerate(channels):
        link = ch[0]
        btn_style = ch[1] if ch[1] and ch[1] != 'normal' else ''
        
        if btn_style:
            row.append(InlineKeyboardButton(f"Join {i+1}", url=link, **{'style': btn_style}))
        else:
            row.append(InlineKeyboardButton(f"Join {i+1}", url=link))
        
        if len(row) == 3:
            markup.add(*row)
            row = []
            
    if row: markup.add(*row)
    
    markup.add(InlineKeyboardButton("✅ Done !!", callback_data="verify_channels", **{'style': 'success'}))
    
    image_url = "https://files.catbox.moe/wcfmqd.jpg" 
    caption = "𝗛ᴇʟʟᴏ 𝗨ꜱᴇʀ 👻 𝐁𝐎𝐓\n\nALL CHANNEL JOIN 🥰\n\n👻 Sab channels join karo phir Done !! dabao"
    bot.send_photo(chat_id, image_url, caption=caption, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "verify_channels")
def verify_callback(call):
    safe_answer(call)
    uid = call.from_user.id
    if is_user_banned(uid): return
    if check_user_status(uid):
        bot.delete_message(call.message.chat.id, call.message.message_id)
        send_main_menu(call.message.chat.id)
    else:
        bot.answer_callback_query(call.id, "❌ Aapne abhi tak channels me Join Request nahi bheji hai!", show_alert=True)

# ================= MAIN MENU & GET KEY LOGIC =================
def send_main_menu(chat_id):
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(KeyboardButton("👤 My Account"), KeyboardButton("🔗 Refer & Earn"))
    markup.add(KeyboardButton("🎁 Get Key (15 Coins)"), KeyboardButton("🔑 Use VIP Key"))
    bot.send_message(chat_id, "✅ Use the menu below to navigate:", reply_markup=markup)

@bot.message_handler(func=lambda m: True)
def text_commands(message):
    uid = message.from_user.id
    if flood_check(uid) or is_user_banned(uid): return
    
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute("SELECT coins FROM v_users WHERE user_id=%s", (uid,))
        res = c.fetchone()
        if not res: return
        coins = res[0]
        text = message.text

        if text == "👤 My Account":
            bot.send_message(uid, f"👤 <b>Account Stats</b>\n\n🆔 User ID: <code>{uid}</code>\n💰 Coins: <b>{coins}</b>")
            
        elif text == "🔗 Refer & Earn":
            bot_usr = bot.get_me().username
            bot.send_message(uid, f"📢 <b>REFER & EARN</b>\n\nInvite friends & get <b>2 Coins</b> per join!\n\n🔗 Your Link:\nhttps://t.me/{bot_usr}?start={uid}")
            
        elif text == "🎁 Get Key (15 Coins)":
            if coins >= 15:
                c.execute("UPDATE v_users SET coins = coins - 15 WHERE user_id=%s", (uid,))
                conn.commit()
                
                req_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                username = message.from_user.username
                user_mention = f"@{username}" if username else f"User ID: {uid}"

                req_text = (
                    f"🆕 <b>New Key Request</b>\n\n"
                    f"👤 <b>User:</b> {user_mention}\n"
                    f"🆔 <b>ID:</b> <code>{uid}</code>\n"
                    f"⏰ <b>Time:</b> {req_time}"
                )

                markup = InlineKeyboardMarkup()
                markup.add(
                    InlineKeyboardButton("✅ APPROVAL", callback_data=f"approve_{uid}", **{'style': 'success'}),
                    InlineKeyboardButton("❌ REJECTED", callback_data=f"reject_{uid}", **{'style': 'danger'})
                )

                try:
                    bot.send_message(APPROVAL_CHANNEL, req_text, reply_markup=markup)
                    success_msg = (
                        "⏳ <b>Request Successfully Sent!</b>\n\n"
                        "Aapki VIP Key ki request Admin ko bhej di gayi hai. Approval milte hi aapko yahin bot me key mil jayegi.\n\n"
                        "⚠️ <b>IMPORTANT WARNING:</b>\n"
                        "Agar aapne <b>@ValiModes_key</b> channel join nahi kiya hai, toh Admin aapki request ko <b>REJECT</b> kar dega aur aapko key nahi milegi!\n\n"
                        "👉 Abhi check karein: @ValiModes_key"
                    )
                    bot.send_message(uid, success_msg)
                except Exception as e:
                    c.execute("UPDATE v_users SET coins = coins + 15 WHERE user_id=%s", (uid,))
                    conn.commit()
                    bot.send_message(uid, f"❌ Error: Admin ne abhi tak bot ko {APPROVAL_CHANNEL} me admin nahi banaya hai. (Coins refunded)")
            else:
                bot.send_message(uid, f"❌ <b>Coins Kam Hain!</b>\n\nKey lene ke liye <b>15 Coins</b> chahiye.\nAapke paas abhi sirf <b>{coins} Coins</b> hain. Doston ko refer karo!")

        elif text == "🔑 Use VIP Key":
            msg = bot.send_message(uid, "Send your generated VIP Key here:")
            bot.register_next_step_handler(msg, process_vip_key)
    finally: release_db(conn)

def process_vip_key(message):
    key = message.text.strip(); uid = message.from_user.id
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute("SELECT duration FROM v_vip_keys WHERE key_code=%s AND status='UNUSED'", (key,))
        res = c.fetchone()
        if res:
            c.execute("UPDATE v_vip_keys SET status='USED', used_by=%s WHERE key_code=%s", (uid, key))
            conn.commit()
            bot.send_message(uid, f"✅ <b>VIP Key Activated!</b>\nYou now have VIP Access for {res[0]} days.")
        else: bot.send_message(uid, "❌ <b>Invalid or Used Key!</b>")
    finally: release_db(conn)

# ================= APPROVE / REJECT LOGIC =================
@bot.callback_query_handler(func=lambda call: call.data.startswith("approve_") or call.data.startswith("reject_"))
def handle_approval(call):
    safe_answer(call)
    if call.from_user.id != ADMIN_ID: return bot.answer_callback_query(call.id, "YE TERE MAI KAM NAHI KAREGA LADLE TO ABHI BACHA HAI", show_alert=True)

    action, uid_str = call.data.split("_")
    uid = int(uid_str)

    if action == "approve":
        try: bot.edit_message_text(f"{call.message.text}\n\n✅ <b>STATUS: APPROVED</b>", chat_id=call.message.chat.id, message_id=call.message.message_id)
        except: pass
        send_dynamic_key(uid)
    elif action == "reject":
        try: bot.edit_message_text(f"{call.message.text}\n\n❌ <b>STATUS: REJECTED</b>", chat_id=call.message.chat.id, message_id=call.message.message_id)
        except: pass
        conn = get_db()
        try:
            c = conn.cursor()
            c.execute("UPDATE v_users SET coins = coins + 15 WHERE user_id=%s", (uid,))
            conn.commit()
        finally: release_db(conn)
        try: bot.send_message(uid, "❌ <b>Request Rejected!</b>\nAdmin ne aapki request reject kar di hai kyunki aapne sab channels join nahi kiye (@ValiModes_key). Aapke 15 coins wapas aa gaye hain.")
        except: pass

# ================= DYNAMIC KEY GENERATOR =================
def send_dynamic_key(chat_id):
    key = f"{random.randint(1000000000, 9999999999)}"
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute("SELECT value FROM v_settings WHERE name='key_link'")
        dynamic_link = c.fetchone()[0]
    finally: release_db(conn)
    text = f"Key - <code>{key}</code>\n\n<a href='https://t.me/+MkNcxGuk-w43MzBl'>DRIP SCINET APK - {dynamic_link}</a>"
    try:
        bot.send_message(chat_id, "🎉 <b>Congratulations!</b>\nAapki request Admin ne Approve kar di hai. Ye rahi aapki key 👇")
        bot.send_message(chat_id, text, disable_web_page_preview=True)
    except: pass

# ================= FLASK WEB SERVER FOR RENDER =================
app = Flask(__name__)
@app.route('/')
def home(): return "🚀 Fast Bot is Live and Running on Render!"

if __name__ == "__main__":
    print("🚀 Fast Telegram Bot Starting...")
    threading.Thread(target=lambda: bot.infinity_polling(skip_pending=True)).start()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
