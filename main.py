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

# ---------------- CONFIG ----------------
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CODE = "13465"

ADMIN_USERS = set()
DELETE_MODE = set()
INPUT_MODE = set()

if not TOKEN:
    raise Exception("BOT_TOKEN missing")

# ---------------- LOGGING ----------------
logging.basicConfig(level=logging.INFO)

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

cursor.execute("""
CREATE UNIQUE INDEX IF NOT EXISTS uniq_reminder
ON reminders(project, text, date, chat_id)
""")

conn.commit()

# ---------------- DATE ----------------
def parse_date(text):
    try:
        return datetime.strptime(text.strip(), "%d %B %Y")
    except:
        return None

# ---------------- SAVE ----------------
def save(project, date, chat_id):
    try:
        cursor.execute("""
            INSERT INTO reminders (project, text, date, chat_id)
            VALUES (?, ?, ?, ?)
        """, (project, project, date, chat_id))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False

# ---------------- GET ----------------
def get_all():
    cursor.execute("SELECT * FROM reminders")
    return cursor.fetchall()

# ---------------- DELETE PROJECT ----------------
def delete_project(project):
    cursor.execute("SELECT COUNT(*) FROM reminders WHERE project=?", (project,))
    count = cursor.fetchone()[0]

    if count == 0:
        return 0

    cursor.execute("DELETE FROM reminders WHERE project=?", (project,))
    conn.commit()
    return count

# ---------------- INPUT ----------------
async def input_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    INPUT_MODE.add(update.effective_chat.id)

    await update.message.reply_text(
        "Send exactly like this:\n\n"
        "Project name: YOUR_PROJECT\n"
        "Delivery date: 26 May 2026"
    )

# ---------------- MESSAGE HANDLER ----------------
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    text = update.message.text.strip()

    # ---------------- DELETE MODE ----------------
    if chat_id in DELETE_MODE:
        project = text

        deleted = delete_project(project)

        DELETE_MODE.remove(chat_id)

        if deleted == 0:
            return await update.message.reply_text("❌ Project not found")

        return await update.message.reply_text(
            f"🗑 Project deleted: {project}\n"
            f"📊 Rows removed: {deleted}\n"
            f"🛠 Manually deleted by admin"
        )

    # ---------------- INPUT MODE ----------------
    if chat_id in INPUT_MODE:
        match = re.search(
            r"Project name:\s*(.+)\s+Delivery date:\s*(.+)",
            text,
            re.IGNORECASE
        )

        if not match:
            return await update.message.reply_text(
                "❌ Wrong format\n\n"
                "Project name: YOUR_PROJECT\n"
                "Delivery date: 26 May 2026"
            )

        project = match.group(1).strip()
        date_text = match.group(2).strip()

        date = parse_date(date_text)

        if not date:
            return await update.message.reply_text("❌ Invalid date")

        ok = save(project, date.strftime("%Y-%m-%d"), chat_id)

        INPUT_MODE.remove(chat_id)

        if ok:
            await update.message.reply_text("✅ Saved successfully!")
        else:
            await update.message.reply_text("⚠️ Duplicate ignored!")

        return

    # ---------------- BLOCK NORMAL TEXT ----------------
    if text.startswith("/"):
        return

    return await update.message.reply_text("❌ Invalid command. Use /input or /admin")

# ---------------- ADMIN PANEL ----------------
async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("Use: /admin <code>")

    if context.args[0] != ADMIN_CODE:
        return await update.message.reply_text("❌ Wrong code")

    ADMIN_USERS.add(update.effective_chat.id)

    keyboard = [
        [InlineKeyboardButton("📦 View DB", callback_data="db")],
        [InlineKeyboardButton("📂 View Projects", callback_data="projects")],
        [InlineKeyboardButton("🗑 Delete a Project", callback_data="delete")],
        [InlineKeyboardButton("🧹 Clear DB", callback_data="clear")]
    ]

    await update.message.reply_text(
        "✅ Admin Panel",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ---------------- BUTTONS ----------------
async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    chat_id = query.message.chat_id

    if chat_id not in ADMIN_USERS:
        return await query.edit_message_text("❌ Not authorized")

    # VIEW DB
    if query.data == "db":
        data = get_all()
        return await query.edit_message_text(str(data))

    # VIEW PROJECTS
    if query.data == "projects":
        cursor.execute("SELECT DISTINCT project FROM reminders")
        data = cursor.fetchall()

        text = "\n".join([d[0] for d in data]) or "No projects"
        return await query.edit_message_text("📂 Projects:\n\n" + text)

    # DELETE MODE
    if query.data == "delete":
        DELETE_MODE.add(chat_id)
        return await query.edit_message_text(
            "🗑 Send the PROJECT NAME to delete:"
        )

    # CLEAR DB
    if query.data == "clear":
        cursor.execute("DELETE FROM reminders")
        conn.commit()
        return await query.edit_message_text("🧹 Database cleared!")

# ---------------- MAIN ----------------
def main():
    print("Bot starting...")

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("input", input_cmd))
    app.add_handler(CommandHandler("admin", admin))

    app.add_handler(CallbackQueryHandler(buttons))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()
