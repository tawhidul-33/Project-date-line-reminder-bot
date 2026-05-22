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

cursor.execute("""
CREATE UNIQUE INDEX IF NOT EXISTS uniq_reminder
ON reminders(project, text, date, chat_id)
""")

conn.commit()

# ---------------- STATE STORAGE ----------------
user_state = {}

# ---------------- HELPERS ----------------
def parse_date(text):
    formats = ["%d %B %Y", "%Y-%m-%d"]
    for f in formats:
        try:
            return datetime.strptime(text, f)
        except:
            pass
    return None


def save_reminder(project, text, date, chat_id):
    try:
        cursor.execute("""
            INSERT INTO reminders (project, text, date, chat_id)
            VALUES (?, ?, ?, ?)
        """, (project, text, date.strftime("%Y-%m-%d"), chat_id))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def get_all():
    cursor.execute("SELECT * FROM reminders")
    return cursor.fetchall()


def delete_project(project):
    cursor.execute("DELETE FROM reminders WHERE project=?", (project,))
    conn.commit()

# ---------------- INPUT FLOW ----------------
async def input_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_chat.id
    user_state[user_id] = {"step": "project"}

    await update.message.reply_text("📌 Project Name দিন:")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_chat.id
    text = update.message.text

    # must start with /input
    if user_id not in user_state:
        return await update.message.reply_text("❌ Please use /input to add reminder")

    state = user_state[user_id]

    # STEP 1: PROJECT
    if state["step"] == "project":
        state["project"] = text
        state["step"] = "date"
        return await update.message.reply_text("📅 Delivery Date দিন (e.g. 26 May 2026):")

    # STEP 2: DATE
    elif state["step"] == "date":
        date = parse_date(text)
        if not date:
            return await update.message.reply_text("❌ Invalid date format")

        state["date"] = date
        state["step"] = "text"
        return await update.message.reply_text("📝 Task / Message লিখুন:")

    # STEP 3: TEXT + SAVE
    elif state["step"] == "text":
        project = state["project"]
        date = state["date"]

        ok = save_reminder(project, text, date, user_id)

        user_state.pop(user_id)

        if ok:
            return await update.message.reply_text("✅ Saved successfully!")
        else:
            return await update.message.reply_text("⚠️ Duplicate ignored!")

# ---------------- ADMIN ----------------
ADMIN_USERS = set()

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

# ---------------- BUTTONS ----------------
async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    chat_id = query.message.chat_id

    if chat_id not in ADMIN_USERS:
        return await query.edit_message_text("❌ Not authorized")

    if query.data == "db":
        data = get_all()
        await query.edit_message_text(str(data))

    elif query.data == "del":
        cursor.execute("SELECT DISTINCT project FROM reminders")
        projects = cursor.fetchall()

        text = "\n".join([p[0] for p in projects]) or "No projects"

        await query.edit_message_text(
            f"📂 Projects:\n\n{text}\n\nUse:\n/del project_name"
        )

    elif query.data == "clear":
        cursor.execute("DELETE FROM reminders")
        conn.commit()
        await query.edit_message_text("🧹 Database cleared!")

# ---------------- DELETE COMMAND ----------------
async def delete_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id not in ADMIN_USERS:
        return await update.message.reply_text("❌ Not admin")

    if not context.args:
        return await update.message.reply_text("Usage: /del <project>")

    project = context.args[0]

    delete_project(project)

    await update.message.reply_text(
        f"🗑 Project '{project}' deleted\n"
        f"🛠 Manually deleted by admin"
    )

# ---------------- MAIN ----------------
def main():
    print("Bot starting...")

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("input", input_cmd))
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(CommandHandler("del", delete_cmd))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(buttons))

    print("Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()
