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

# ---------------- DATABASE ----------------
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

# Prevent duplicates
cursor.execute("""
CREATE UNIQUE INDEX IF NOT EXISTS uniq_reminder
ON reminders(project, text, date, chat_id)
""")

conn.commit()

# ---------------- INPUT SESSION ----------------
user_input_mode = set()

# ---------------- DATE PARSER ----------------
def parse_date(text):
    try:
        return datetime.strptime(text.strip(), "%d %B %Y")
    except:
        return None


# ---------------- SAVE ----------------
def save_reminder(project, text, date, chat_id):
    try:
        cursor.execute("""
            INSERT INTO reminders (project, text, date, chat_id)
            VALUES (?, ?, ?, ?)
        """, (project, text, date, chat_id))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False


# ---------------- DELETE PROJECT ----------------
def delete_project(project):
    cursor.execute("SELECT COUNT(*) FROM reminders WHERE project=?", (project,))
    count = cursor.fetchone()[0]

    cursor.execute("DELETE FROM reminders WHERE project=?", (project,))
    conn.commit()

    return count


# ---------------- INPUT COMMAND ----------------
async def input_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_input_mode.add(update.effective_chat.id)

    await update.message.reply_text(
        "Send data in EXACT format:\n\n"
        "Project name: YOUR_PROJECT\n"
        "Delivery date: 26 May 2026"
    )


# ---------------- MESSAGE HANDLER ----------------
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    text = update.message.text.strip()

    # Ignore if not in input mode
    if chat_id not in user_input_mode:
        return

    # Validate format
    match = re.search(
        r"Project name:\s*(.+)\s+Delivery date:\s*(.+)",
        text,
        re.IGNORECASE
    )

    if not match:
        return await update.message.reply_text(
            "❌ Wrong format!\n\n"
            "Correct format:\n"
            "Project name: YOUR_PROJECT\n"
            "Delivery date: 26 May 2026"
        )

    project = match.group(1).strip()
    date_text = match.group(2).strip()

    date = parse_date(date_text)

    if not date:
        return await update.message.reply_text(
            "❌ Invalid date format!\nUse: 26 May 2026"
        )

    ok = save_reminder(
        project,
        project,   # text = project (simple)
        date.strftime("%Y-%m-%d"),
        chat_id
    )

    user_input_mode.remove(chat_id)

    if ok:
        await update.message.reply_text("✅ Saved successfully!")
    else:
        await update.message.reply_text("⚠️ Duplicate detected!")


# ---------------- ADMIN PANEL ----------------
async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("Use: /admin <code>")

    if context.args[0] != ADMIN_CODE:
        return await update.message.reply_text("❌ Wrong code")

    keyboard = [
        [InlineKeyboardButton("📦 View DB", callback_data="db")],
        [InlineKeyboardButton("📋 View Projects", callback_data="view")],
        [InlineKeyboardButton("🧹 Clear DB", callback_data="clear")]
    ]

    await update.message.reply_text(
        "✅ Admin Panel",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ---------------- DELETE COMMAND ----------------
async def delete_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id not in ADMIN_USERS:
        return await update.message.reply_text("❌ Not admin")

    if not context.args:
        return await update.message.reply_text("Usage: /del <project>")

    project = " ".join(context.args)

    cursor.execute("SELECT COUNT(*) FROM reminders WHERE project=?", (project,))
    count = cursor.fetchone()[0]

    if count == 0:
        return await update.message.reply_text("❌ Project not found")

    deleted = delete_project(project)

    await update.message.reply_text(
        f"🗑 Deleted project: {project}\n"
        f"Rows removed: {deleted}\n"
        f"Manually deleted by admin"
    )


# ---------------- BUTTONS ----------------
async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    chat_id = query.message.chat_id

    if query.data == "db":
        cursor.execute("SELECT * FROM reminders")
        data = cursor.fetchall()
        await query.edit_message_text(str(data))

    elif query.data == "view":
        cursor.execute("SELECT DISTINCT project FROM reminders")
        projects = cursor.fetchall()
        text = "\n".join([p[0] for p in projects]) or "No projects"
        await query.edit_message_text(text)

    elif query.data == "clear":
        cursor.execute("DELETE FROM reminders")
        conn.commit()
        await query.edit_message_text("🧹 Database cleared!")


# ---------------- JOB (DISABLED SAFE) ----------------
def start_jobs(app):
    pass


# ---------------- MAIN ----------------
def main():
    print("Bot starting...")

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(CommandHandler("input", input_cmd))
    app.add_handler(CommandHandler("del", delete_cmd))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(buttons))

    start_jobs(app)

    print("Bot running...")
    app.run_polling()


if __name__ == "__main__":
    main()
