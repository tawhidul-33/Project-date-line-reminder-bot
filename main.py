import os
import re
import sqlite3
import logging
from datetime import datetime, timedelta

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    MessageHandler,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    filters
)

# ---------------- LOGGING ----------------
logging.basicConfig(level=logging.INFO)

# ---------------- CONFIG ----------------
TOKEN = os.getenv("BOT_TOKEN")

ADMIN_CODE = "13465"   # 🔐 change this
ADMIN_USERS = set()

if not TOKEN:
    raise Exception("BOT_TOKEN missing")

# ---------------- DB ----------------
conn = sqlite3.connect("reminders.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT,
    date TEXT,
    chat_id INTEGER,
    phase TEXT DEFAULT 'new'
)
""")
conn.commit()

# ---------------- DATE PARSER ----------------
def extract_date(text):
    patterns = [
        r"(\d{1,2} \w+ \d{4})",
        r"(\d{4}-\d{2}-\d{2})"
    ]

    for p in patterns:
        m = re.search(p, text)
        if m:
            try:
                return datetime.strptime(m.group(1), "%d %B %Y")
            except:
                try:
                    return datetime.strptime(m.group(1), "%Y-%m-%d")
                except:
                    pass
    return None

# ---------------- SAVE ----------------
def save_reminder(text, date, chat_id):
    date_str = date.strftime("%Y-%m-%d")

    cursor.execute("""
        SELECT id FROM reminders 
        WHERE text=? AND date=? AND chat_id=?
    """, (text, date_str, chat_id))

    if cursor.fetchone():
        return False

    cursor.execute("""
        INSERT INTO reminders (text, date, chat_id)
        VALUES (?, ?, ?)
    """, (text, date_str, chat_id))

    conn.commit()
    return True

# ---------------- GET ALL ----------------
def get_all():
    cursor.execute("SELECT * FROM reminders")
    return cursor.fetchall()

# ---------------- MESSAGE ----------------
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    chat_id = update.effective_chat.id

    date = extract_date(text)

    if date:
        ok = save_reminder(text, date, chat_id)

        if ok:
            await update.message.reply_text("✅ Saved successfully!")
        else:
            await update.message.reply_text("⚠️ Already exists!")

# ---------------- SMART ALERT ----------------
async def check_reminders(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now().date()

    cursor.execute("SELECT id, text, date, chat_id, phase FROM reminders")
    rows = cursor.fetchall()

    for r in rows:
        rid, text, date_str, chat_id, phase = r
        rdate = datetime.strptime(date_str, "%Y-%m-%d").date()
        diff = (rdate - now).days

        # 3 DAYS ALERT (repeat every 3h)
        if diff == 3:
            cursor.execute("UPDATE reminders SET phase='3d' WHERE id=?", (rid,))
            conn.commit()

            await context.bot.send_message(
                chat_id=chat_id,
                text=f"📢 3 DAYS LEFT\n\n{text}"
            )

        # 2 DAYS ALERT (repeat every 3h)
        elif diff == 2:
            cursor.execute("UPDATE reminders SET phase='2d' WHERE id=?", (rid,))
            conn.commit()

            await context.bot.send_message(
                chat_id=chat_id,
                text=f"⚠️ 2 DAYS LEFT\n\n{text}"
            )

        # DELETE ONCE ONLY
        elif diff < 0 and phase != "deleted":
            cursor.execute("UPDATE reminders SET phase='deleted' WHERE id=?", (rid,))
            conn.commit()

            await context.bot.send_message(
                chat_id=chat_id,
                text=f"❌ DEADLINE OVER\n\n{text}"
            )

# ---------------- ADMIN ----------------
async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("Use: /admin <code>")

    code = context.args[0]

    if code != ADMIN_CODE:
        return await update.message.reply_text("❌ Wrong code")

    ADMIN_USERS.add(update.effective_chat.id)

    keyboard = [
        [InlineKeyboardButton("📦 View DB", callback_data="db")],
        [InlineKeyboardButton("📋 View Reminders", callback_data="rem")],
        [InlineKeyboardButton("🧹 Clear DB", callback_data="clear")]
    ]

    await update.message.reply_text(
        "✅ Admin Panel",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ---------------- BUTTON HANDLER ----------------
async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    chat_id = query.message.chat_id

    if chat_id not in ADMIN_USERS:
        return await query.edit_message_text("❌ Not authorized")

    if query.data == "db":
        data = get_all()
        await query.edit_message_text(str(data))

    elif query.data == "rem":
        cursor.execute("SELECT text, date FROM reminders")
        data = cursor.fetchall()
        await query.edit_message_text(str(data))

    elif query.data == "clear":
        cursor.execute("DELETE FROM reminders")
        conn.commit()
        await query.edit_message_text("🧹 Database cleared!")

# ---------------- JOB ----------------
def start_jobs(app):
    app.job_queue.run_repeating(check_reminders, interval=10800, first=10)

# ---------------- MAIN ----------------
def main():
    print("Bot starting...")

    app = Application.builder().token(TOKEN).build()

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(CallbackQueryHandler(buttons))

    start_jobs(app)

    print("Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()
