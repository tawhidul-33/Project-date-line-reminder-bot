import os
import re
import sqlite3
import logging
from datetime import datetime

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
ADMIN_CODE = "13465"
ADMIN_USERS = set()

if not TOKEN:
    raise Exception("BOT_TOKEN missing")

# ---------------- DB ----------------
conn = sqlite3.connect("reminders.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project TEXT,
    text TEXT,
    date TEXT,
    chat_id INTEGER,
    phase TEXT DEFAULT 'new'
)
""")

# UNIQUE (no duplicate same project + same date + same chat)
cursor.execute("""
CREATE UNIQUE INDEX IF NOT EXISTS uniq_reminder
ON reminders(project, text, date, chat_id)
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

# ---------------- PROJECT PARSER ----------------
def extract_project(text):
    # format: [project] message 12 January 2026
    match = re.match(r"\[(.*?)\]\s*(.*)", text)
    if match:
        return match.group(1).strip(), match.group(2).strip()
    return "default", text

# ---------------- SAVE ----------------
def save_reminder(project, text, date, chat_id):
    date_str = date.strftime("%Y-%m-%d")

    try:
        cursor.execute("""
            INSERT INTO reminders (project, text, date, chat_id)
            VALUES (?, ?, ?, ?)
        """, (project, text, date_str, chat_id))

        conn.commit()
        return True

    except sqlite3.IntegrityError:
        return False

# ---------------- GET ALL ----------------
def get_all():
    cursor.execute("SELECT * FROM reminders")
    return cursor.fetchall()

# ---------------- DELETE PROJECT ----------------
def delete_project(project_name):
    cursor.execute("SELECT COUNT(*) FROM reminders WHERE project=?", (project_name,))
    count = cursor.fetchone()[0]

    cursor.execute("DELETE FROM reminders WHERE project=?", (project_name,))
    conn.commit()

    return count

# ---------------- MESSAGE HANDLER ----------------
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    chat_id = update.effective_chat.id

    date = extract_date(text)
    if not date:
        return await update.message.reply_text("❌ No valid date found")

    project, clean_text = extract_project(text)

    ok = save_reminder(project, clean_text, date, chat_id)

    if ok:
        await update.message.reply_text("✅ Saved successfully!")
    else:
        await update.message.reply_text("⚠️ Duplicate ignored!")

# ---------------- ADMIN ----------------
async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("Use: /admin <code>")

    if context.args[0] != ADMIN_CODE:
        return await update.message.reply_text("❌ Wrong code")

    ADMIN_USERS.add(update.effective_chat.id)

    keyboard = [
        [InlineKeyboardButton("📦 View DB", callback_data="db")],
        [InlineKeyboardButton("🗑 Delete Project", callback_data="del")],
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

    # VIEW DB
    if query.data == "db":
        data = get_all()
        await query.edit_message_text(str(data))

    # DELETE PROJECT (manual input)
    elif query.data == "del":
        cursor.execute("SELECT DISTINCT project FROM reminders")
        projects = cursor.fetchall()

        text = "\n".join([p[0] for p in projects]) or "No projects"

        await query.edit_message_text(
            f"📂 Projects:\n\n{text}\n\nSend: /del project_name"
        )

    # CLEAR DB
    elif query.data == "clear":
        cursor.execute("DELETE FROM reminders")
        conn.commit()
        await query.edit_message_text("🧹 Database cleared!")

# ---------------- COMMAND: DELETE PROJECT ----------------
async def delete_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id not in ADMIN_USERS:
        return await update.message.reply_text("❌ Not admin")

    if not context.args:
        return await update.message.reply_text("Usage: /del <project>")

    project = context.args[0]

    count = delete_project(project)

    await update.message.reply_text(
        f"🗑 Project '{project}' deleted\n"
        f"📊 Removed rows: {count}\n\n"
        f"🛠 Manually deleted by admin"
    )

# ---------------- JOB ----------------
def start_jobs(app):
    if app.job_queue:
        app.job_queue.run_repeating(lambda c: None, interval=999999, first=10)

# ---------------- MAIN ----------------
def main():
    print("Bot starting...")

    app = Application.builder().token(TOKEN).build()

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(CommandHandler("del", delete_cmd))
    app.add_handler(CallbackQueryHandler(buttons))

    start_jobs(app)

    print("Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()
