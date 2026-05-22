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
INPUT_MODE = set()
DELETE_MODE = set()

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
    user_id INTEGER,
    project TEXT,
    text TEXT,
    date TEXT,
    phase TEXT DEFAULT 'new'
)
""")

cursor.execute("""
CREATE UNIQUE INDEX IF NOT EXISTS uniq_reminder
ON reminders(user_id, project, date)
""")

conn.commit()

# ---------------- DATE ----------------
def parse_date(text):
    try:
        return datetime.strptime(text.strip(), "%d %B %Y")
    except:
        return None

# ---------------- SAVE ----------------
def save(user_id, project, date):
    try:
        cursor.execute("""
            INSERT INTO reminders (user_id, project, text, date)
            VALUES (?, ?, ?, ?)
        """, (user_id, project, project, date))

        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False

# ---------------- GET USER DATA ----------------
def get_user_projects(user_id):
    cursor.execute("SELECT DISTINCT project FROM reminders WHERE user_id=?", (user_id,))
    return cursor.fetchall()

# ---------------- GET ALL ----------------
def get_all():
    cursor.execute("SELECT * FROM reminders")
    return cursor.fetchall()

# ---------------- DELETE USER PROJECT ----------------
def delete_user_project(user_id, project):
    cursor.execute(
        "SELECT COUNT(*) FROM reminders WHERE user_id=? AND project=?",
        (user_id, project)
    )
    count = cursor.fetchone()[0]

    cursor.execute(
        "DELETE FROM reminders WHERE user_id=? AND project=?",
        (user_id, project)
    )
    conn.commit()

    return count

# ---------------- ADMIN DELETE ----------------
def admin_delete_project(project):
    cursor.execute("SELECT DISTINCT user_id FROM reminders WHERE project=?", (project,))
    users = cursor.fetchall()

    cursor.execute("DELETE FROM reminders WHERE project=?", (project,))
    conn.commit()

    return [u[0] for u in users]

# ---------------- INPUT ----------------
async def input_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    INPUT_MODE.add(update.effective_chat.id)

    await update.message.reply_text(
        "Send exactly like this:\n\n"
        "Project name: YOUR_PROJECT\n"
        "Delivery date: 26 May 2026"
    )

# ---------------- MESSAGE ----------------
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    text = update.message.text.strip()

    # ---------------- USER INPUT ----------------
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
            return await update.message.reply_text("❌ Invalid date format")

        ok = save(chat_id, project, date.strftime("%Y-%m-%d"))

        INPUT_MODE.remove(chat_id)

        if ok:
            await update.message.reply_text("✅ Saved successfully!")
        else:
            await update.message.reply_text("⚠️ Duplicate ignored!")

        return

    # ---------------- USER DELETE ----------------
    if chat_id in DELETE_MODE:
        project = text

        deleted = delete_user_project(chat_id, project)
        DELETE_MODE.remove(chat_id)

        if deleted == 0:
            return await update.message.reply_text("❌ Project not found")

        return await update.message.reply_text(
            f"🗑 Deleted: {project}\nRows removed: {deleted}"
        )

# ---------------- USER PANEL ----------------
async def user_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    keyboard = [
        [InlineKeyboardButton("📂 My Projects", callback_data="my")],
        [InlineKeyboardButton("🗑 Delete Project", callback_data="mydel")],
        [InlineKeyboardButton("🧹 Clear My Data", callback_data="myclear")]
    ]

    await update.message.reply_text(
        "👤 User Panel",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ---------------- ADMIN ----------------
async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or context.args[0] != ADMIN_CODE:
        return await update.message.reply_text("❌ Wrong code")

    ADMIN_USERS.add(update.effective_chat.id)

    keyboard = [
        [InlineKeyboardButton("📦 View DB", callback_data="db")],
        [InlineKeyboardButton("📂 View Projects", callback_data="projects")],
        [InlineKeyboardButton("🗑 Delete Project", callback_data="adel")],
        [InlineKeyboardButton("🧹 Clear DB", callback_data="clear")]
    ]

    await update.message.reply_text(
        "👑 Admin Panel",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ---------------- BUTTONS ----------------
async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    chat_id = query.message.chat_id

    # ---------------- USER ACTIONS ----------------
    if query.data == "my":
        data = get_user_projects(chat_id)
        text = "\n".join([d[0] for d in data]) or "No projects"
        return await query.edit_message_text("📂 Your Projects:\n\n" + text)

    if query.data == "mydel":
        DELETE_MODE.add(chat_id)
        return await query.edit_message_text("Send project name to delete:")

    if query.data == "myclear":
        cursor.execute("DELETE FROM reminders WHERE user_id=?", (chat_id,))
        conn.commit()
        return await query.edit_message_text("🧹 Your data cleared!")

    # ---------------- ADMIN ACTIONS ----------------
    if chat_id not in ADMIN_USERS:
        return await query.edit_message_text("❌ Not authorized")

    if query.data == "db":
        return await query.edit_message_text(str(get_all()))

    if query.data == "projects":
        cursor.execute("SELECT DISTINCT project FROM reminders")
        data = cursor.fetchall()
        text = "\n".join([d[0] for d in data]) or "No projects"
        return await query.edit_message_text(text)

    if query.data == "adel":
        cursor.execute("SELECT DISTINCT project FROM reminders")
        data = cursor.fetchall()
        text = "\n".join([d[0] for d in data])
        return await query.edit_message_text(
            "Send project name to delete:\n\n" + text
        )

    if query.data == "clear":
        cursor.execute("DELETE FROM reminders")
        conn.commit()
        return await query.edit_message_text("🧹 DB cleared!")

# ---------------- MAIN ----------------
def main():
    print("Bot starting...")

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("input", input_cmd))
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(CommandHandler("user", user_panel))

    app.add_handler(CallbackQueryHandler(buttons))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()
