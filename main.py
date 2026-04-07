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
TOKEN = '8579040508:AAGJ90ZJi62kXCKKtcJ3kR2oO7NdwLXUJ3A'
DATABASE_URL = "postgresql://postgres.jhhmwbivhohvcicyuxqe:mQcGVnP7gMFHQjYE@aws-1-ap-southeast-1.pooler.supabase.com:6543/postgres?sslmode=require"

ADMIN_ID = 1484173564
APPROVAL_CHANNEL = "@ValiModes_key" 

# Ultra-Fast Polling with 20 Threads
bot = telebot.TeleBot(TOKEN, parse_mode='HTML', num_threads=20)

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
    # 20 connection pool for high traffic
    db_pool = ThreadedConnectionPool(1, 25, DATABASE_URL)
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
        c.execute("INSERT INTO v_settings (name, value) VALUES ('key_link', 'https://www.mediafire.com/file/if3uvvwjbj87lo2/DRIPCLIENT_v6.2_GLOBAL_AP.apks/file') ON CONFLICT (name) DO NOTHING")
        conn.commit()
    finally: release_db(conn)

init_db()

# ================= SECURITY / ANTI-SPAM =================
user_last_msg = {}
temp_bulk_channels = {} 

def flood_check(user_id):
    now = time.time()
    if user_id in user_last_msg and now - user_last_msg[user_id] < 0.6: return True # Faster msg threshold
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

# ================= 💰 ADMIN COMMANDS =================
@bot.message_handler(commands=['addcoins'])
def add_coins(message):
    if message.chat.id != ADMIN_ID: return
    try:
        parts = message.text.split()
        target_user, amount = int(parts[1]), int(parts[2])
        conn = get_db()
        try:
            c = conn.cursor()
            c.execute("UPDATE v_users SET coins = coins + %s WHERE user_id=%s", (amount, target_user))
            conn.commit()
        finally: release_db(conn)
        bot.reply_to(message, f"✅ <b>{amount} Coins</b> added to {target_user}.")
    except: bot.reply_to(message, "❌ Use: `/addcoins ID AMOUNT`")

@bot.message_handler(commands=['change'])
def change_link(message):
    if message.chat.id != ADMIN_ID: return
    new_link = message.text.replace('/change', '').strip()
    if not new_link: return
    conn = get_db()
    try:
        c = conn.cursor(); c.execute("UPDATE v_settings SET value=%s WHERE name='key_link'", (new_link,))
        conn.commit()
    finally: release_db(conn)
    bot.reply_to(message, "✅ Link Updated!")

# ================= ADMIN PANEL (BULK ADD) =================
@bot.message_handler(commands=['admin'])
def admin_panel(message):
    if message.chat.id != ADMIN_ID: return 
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(InlineKeyboardButton("➕ Bulk Add Channels", callback_data="add_bulk"),
               InlineKeyboardButton("➖ Remove Channel", callback_data="remove_channel", style="danger"))
    markup.add(InlineKeyboardButton("📋 View Channels", callback_data="view_channels", style="success"),
               InlineKeyboardButton("📊 Stats", callback_data="adm_stats", style="primary"))
    markup.add(InlineKeyboardButton("📢 Broadcast", callback_data="adm_broadcast", style="success"),
               InlineKeyboardButton("🚫 Ban User", callback_data="adm_ban", style="danger"))
    bot.send_message(message.chat.id, "👨‍💻 <b>Boss Admin Panel</b>", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data in ["add_bulk", "remove_channel", "view_channels"] or call.data.startswith("adm_") or call.data.startswith("bulkstyle_"))
def admin_callbacks(call):
    if call.message.chat.id != ADMIN_ID: return
    safe_answer(call)

    # 🎨 BULK COLOR APPLY LOGIC
    if call.data.startswith("bulkstyle_"):
        style = call.data.split("_")[1]
        channels_to_add = temp_bulk_channels.get(call.message.chat.id, [])
        if not channels_to_add: return
        
        conn = get_db()
        try:
            c = conn.cursor()
            for ch in channels_to_add:
                c.execute("INSERT INTO v_channels (channel_id, link, style) VALUES (%s, %s, %s) ON CONFLICT (channel_id) DO UPDATE SET link=EXCLUDED.link, style=EXCLUDED.style", (ch['id'], ch['link'], style))
            conn.commit()
        finally: release_db(conn)
        
        bot.edit_message_text(f"✅ <b>{len(channels_to_add)} Channels</b> successfully add ho gaye!\n🎨 Color Applied: {style.upper()}", chat_id=call.message.chat.id, message_id=call.message.message_id)
        temp_bulk_channels[call.message.chat.id] = []
        return

    if call.data == "add_bulk":
        msg = bot.send_message(call.message.chat.id, "📝 Sabhi Channel IDs bhejiye (space ya newline dekar).\nExample:\n-100123\n-100456\n-100789")
        bot.register_next_step_handler(msg, process_bulk_add)
        
    elif call.data == "view_channels":
        conn = get_db()
        try:
            c = conn.cursor(); c.execute("SELECT channel_id, link, style FROM v_channels"); channels = c.fetchall()
        finally: release_db(conn)
        if not channels: return bot.send_message(call.message.chat.id, "❌ No channels.")
        text = "📋 <b>Added Channels:</b>\n"
        for ch in channels: text += f"ID: <code>{ch[0]}</code> | {ch[2].upper()}\n"
        bot.send_message(call.message.chat.id, text)
        
    elif call.data == "adm_stats":
        conn = get_db()
        try:
            c = conn.cursor(); c.execute("SELECT COUNT(*) FROM v_users"); tot = c.fetchone()[0]
        finally: release_db(conn)
        bot.send_message(call.message.chat.id, f"👥 Total Users: {tot}")

def process_bulk_add(message):
    ids = message.text.replace(',', ' ').split()
    valid_channels = []
    bot_msg = bot.send_message(message.chat.id, f"⏳ {len(ids)} IDs process ho rahi hain...")
    
    for ch_id in ids:
        try:
            bot_member = bot.get_chat_member(ch_id, bot.get_me().id)
            if bot_member.status in ['administrator', 'creator']:
                link = bot.create_chat_invite_link(ch_id, creates_join_request=True).invite_link
                valid_channels.append({'id': ch_id, 'link': link})
        except: continue
    
    if not valid_channels:
        return bot.edit_message_text("❌ Koi bhi ID sahi nahi mili ya Bot Admin nahi hai.", chat_id=message.chat.id, message_id=bot_msg.message_id)

    temp_bulk_channels[message.chat.id] = valid_channels
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🔵 Blue", callback_data="bulkstyle_primary", **{'style': 'primary'}),
        InlineKeyboardButton("🟢 Green", callback_data="bulkstyle_success", **{'style': 'success'}),
        InlineKeyboardButton("🔴 Red", callback_data="bulkstyle_danger", **{'style': 'danger'}),
        InlineKeyboardButton("⚪ Normal", callback_data="bulkstyle_normal")
    )
    bot.edit_message_text(f"✅ {len(valid_channels)} Channels taiyar hain!\n🎨 In sab ke liye <b>kaunsa color</b> rakhna hai?", chat_id=message.chat.id, message_id=bot_msg.message_id, reply_markup=markup)

# ================= JOIN REQUEST & FORCE SUB =================
@bot.chat_join_request_handler()
def handle_join_request(message: telebot.types.ChatJoinRequest):
    conn = get_db()
    try:
        c = conn.cursor(); c.execute("INSERT INTO v_join_reqs (user_id, channel_id) VALUES (%s, %s)", (message.from_user.id, str(message.chat.id)))
        conn.commit()
    finally: release_db(conn)

@bot.message_handler(commands=['start'])
def start_cmd(message):
    uid = message.from_user.id
    if flood_check(uid) or is_user_banned(uid): return

    conn = get_db()
    try:
        c = conn.cursor(); c.execute("SELECT * FROM v_users WHERE user_id=%s", (uid,))
        if not c.fetchone():
            date = datetime.now().strftime("%Y-%m-%d")
            c.execute("INSERT INTO v_users (user_id, username, join_date) VALUES (%s, %s, %s)", (uid, message.from_user.username or "Unknown", date))
            args = message.text.split()
            if len(args) > 1 and args[1].isdigit():
                ref_id = int(args[1])
                if ref_id != uid:
                    c.execute("UPDATE v_users SET coins = coins + 2 WHERE user_id=%s", (ref_id,))
                    try: bot.send_message(ref_id, "🎉 <b>Congrats!</b> +2 Coins Added!")
                    except: pass
            conn.commit()
    finally: release_db(conn)
    send_force_sub(message.chat.id, uid)

def check_user_status(user_id):
    conn = get_db()
    try:
        c = conn.cursor(); c.execute("SELECT channel_id FROM v_channels"); channels = c.fetchall()
        if not channels: return True 
        for ch in channels:
            try:
                if bot.get_chat_member(ch[0], user_id).status in ['member', 'administrator', 'creator']: continue
            except: pass
            c.execute("SELECT * FROM v_join_reqs WHERE user_id=%s AND channel_id=%s", (user_id, ch[0]))
            if not c.fetchone(): return False 
        return True
    finally: release_db(conn)

def send_force_sub(chat_id, user_id):
    if check_user_status(user_id): return send_main_menu(chat_id)
    markup = InlineKeyboardMarkup()
    conn = get_db()
    try:
        c = conn.cursor(); c.execute("SELECT link, style FROM v_channels"); channels = c.fetchall()
    finally: release_db(conn)
    
    row = []
    for i, ch in enumerate(channels):
        link = ch[0]; btn_style = ch[1] if ch[1] and ch[1] != 'normal' else ''
        if btn_style: row.append(InlineKeyboardButton(f"Join {i+1}", url=link, **{'style': btn_style}))
        else: row.append(InlineKeyboardButton(f"Join {i+1}", url=link))
        if len(row) == 3: markup.add(*row); row = []
    if row: markup.add(*row)
    markup.add(InlineKeyboardButton("✅ Done !!", callback_data="verify_channels", **{'style': 'success'}))
    bot.send_photo(chat_id, "https://files.catbox.moe/wcfmqd.jpg", caption="𝗛ᴇʟʟᴏ 𝗨ꜱᴇʀ 👻\n\nALL CHANNEL JOIN 🥰", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "verify_channels")
def verify_callback(call):
    safe_answer(call)
    if check_user_status(call.from_user.id):
        bot.delete_message(call.message.chat.id, call.message.message_id)
        send_main_menu(call.message.chat.id)
    else: bot.answer_callback_query(call.id, "❌ Join Request nahi bheji aapne!", show_alert=True)

# ================= MAIN MENU =================
def send_main_menu(chat_id):
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(KeyboardButton("👤 My Account"), KeyboardButton("🔗 Refer & Earn"))
    markup.add(KeyboardButton("🎁 Get Key (15 Coins)"), KeyboardButton("🔑 Use VIP Key"))
    bot.send_message(chat_id, "✅ Choose an option:", reply_markup=markup)

@bot.message_handler(func=lambda m: True)
def text_commands(message):
    uid = message.from_user.id
    if flood_check(uid) or is_user_banned(uid): return
    conn = get_db()
    try:
        c = conn.cursor(); c.execute("SELECT coins FROM v_users WHERE user_id=%s", (uid,)); res = c.fetchone()
        if not res: return
        coins = res[0]; text = message.text
        if text == "👤 My Account": bot.send_message(uid, f"👤 <b>ID:</b> <code>{uid}</code>\n💰 <b>Coins:</b> {coins}")
        elif text == "🔗 Refer & Earn": bot.send_message(uid, f"🔗 <b>Your Link:</b>\nhttps://t.me/{bot.get_me().username}?start={uid}")
        elif text == "🎁 Get Key (15 Coins)":
            if coins >= 15:
                c.execute("UPDATE v_users SET coins = coins - 15 WHERE user_id=%s", (uid,)); conn.commit()
                markup = InlineKeyboardMarkup().add(InlineKeyboardButton("✅ APPROVE", callback_data=f"approve_{uid}", **{'style': 'success'}), InlineKeyboardButton("❌ REJECT", callback_data=f"reject_{uid}", **{'style': 'danger'}))
                bot.send_message(APPROVAL_CHANNEL, f"🆕 New Key Request from <code>{uid}</code>", reply_markup=markup)
                bot.send_message(uid, "⏳ Request sent to Admin!")
            else: bot.send_message(uid, f"❌ Need 15 Coins (You have {coins})")
    finally: release_db(conn)

@bot.callback_query_handler(func=lambda call: call.data.startswith("approve_") or call.data.startswith("reject_"))
def handle_approval(call):
    if call.from_user.id != ADMIN_ID: return safe_answer(call)
    action, uid = call.data.split("_")
    if action == "approve":
        key = f"{random.randint(1000000000, 9999999999)}"
        bot.send_message(int(uid), f"🎉 <b>Approved!</b>\nKey: <code>{key}</code>")
        bot.edit_message_text(f"{call.message.text}\n✅ Approved", call.message.chat.id, call.message.message_id)
    else:
        conn = get_db()
        try:
            c = conn.cursor(); c.execute("UPDATE v_users SET coins = coins + 15 WHERE user_id=%s", (int(uid),)); conn.commit()
        finally: release_db(conn)
        bot.send_message(int(uid), "❌ Request Rejected! Coins Refunded.")
        bot.edit_message_text(f"{call.message.text}\n❌ Rejected", call.message.chat.id, call.message.message_id)

# ================= SERVER =================
app = Flask(__name__)
@app.route('/')
def home(): return "Rocket Bot is Live!"

if __name__ == "__main__":
    threading.Thread(target=lambda: bot.infinity_polling(skip_pending=True)).start()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
