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

# Separate delete modes
USER_DELETE_MODE = set()
ADMIN_DELETE_MODE = set()

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
    project = project.strip().lower()

    try:
        cursor.execute("""
            INSERT INTO reminders (user_id, project, text, date)
            VALUES (?, ?, ?, ?)
        """, (user_id, project, project, date))

        conn.commit()
        return True

    except sqlite3.IntegrityError:
        return False

# ---------------- USER PROJECTS ----------------
def get_user_projects(user_id):
    cursor.execute(
        "SELECT DISTINCT project FROM reminders WHERE user_id=?",
        (user_id,)
    )
    return cursor.fetchall()

# ---------------- DELETE USER PROJECT ----------------
def delete_user_project(user_id, project):
    project = project.strip().lower()

    cursor.execute(
        "SELECT COUNT(*) FROM reminders WHERE user_id=? AND project=?",
        (user_id, project)
    )

    count = cursor.fetchone()[0]

    if count == 0:
        return 0

    cursor.execute(
        "DELETE FROM reminders WHERE user_id=? AND project=?",
        (user_id, project)
    )

    conn.commit()
    return count

# ---------------- ADMIN DELETE ----------------
def admin_delete_project(project):
    project = project.strip().lower()

    cursor.execute(
        "SELECT DISTINCT user_id FROM reminders WHERE project=?",
        (project,)
    )

    users = cursor.fetchall()

    if not users:
        return []

    cursor.execute(
        "DELETE FROM reminders WHERE project=?",
        (project,)
    )

    conn.commit()

    return [u[0] for u in users]

# ---------------- INPUT ----------------
async def input_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    INPUT_MODE.add(update.effective_chat.id)

    await update.message.reply_text(
        "Project name: YOUR_PROJECT\n"
        "Delivery date: 26 May 2026"
    )

# ---------------- USER PANEL ----------------
async def user_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):

    keyboard = [
        [InlineKeyboardButton("📂 My Projects", callback_data="my")],
        [InlineKeyboardButton("🗑 Delete Project", callback_data="mydel")],
        [InlineKeyboardButton("🧹 Clear My Data", callback_data="myclear")]
    ]

    await update.message.reply_text(
        "👤 User Panel",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ---------------- ADMIN PANEL ----------------
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

# ---------------- MESSAGE HANDLER ----------------
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):

    chat_id = update.effective_chat.id
    text = update.message.text.strip()

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
                "Use:\n"
                "Project name: YOUR_PROJECT\n"
                "Delivery date: 26 May 2026"
            )

        project = match.group(1).strip().lower()
        date_text = match.group(2).strip()

        date = parse_date(date_text)

        if not date:
            return await update.message.reply_text("❌ Invalid date")

        ok = save(chat_id, project, date.strftime("%Y-%m-%d"))

        INPUT_MODE.remove(chat_id)

        if ok:
            return await update.message.reply_text("✅ Saved successfully!")

        return await update.message.reply_text("⚠️ Duplicate ignored!")

    # ---------------- USER DELETE ----------------
    if chat_id in USER_DELETE_MODE:

        project = text.strip().lower()

        deleted = delete_user_project(chat_id, project)

        USER_DELETE_MODE.remove(chat_id)

        if deleted == 0:
            return await update.message.reply_text("❌ Project not found")

        return await update.message.reply_text(
            f"🗑 Deleted project: {project}"
        )

    # ---------------- ADMIN DELETE ----------------
    if chat_id in ADMIN_DELETE_MODE:

        project = text.strip().lower()

        users = admin_delete_project(project)

        ADMIN_DELETE_MODE.remove(chat_id)

        if not users:
            return await update.message.reply_text("❌ Project not found")

        # Send message to affected users
        for user_id in users:
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"❌ Your project '{project}' was deleted by admin"
                )
            except:
                pass

        return await update.message.reply_text(
            f"🗑 Project deleted: {project}"
        )

    # ---------------- WRONG COMMAND ----------------
    await update.message.reply_text(
        "❌ Wrong input\n\n"
        "Use:\n"
        "/input\n"
        "/user\n"
        "/admin CODE"
    )

# ---------------- BUTTONS ----------------
async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    chat_id = query.message.chat_id

    # ---------------- USER BUTTONS ----------------
    if query.data == "my":

        data = get_user_projects(chat_id)

        text = "\n".join([d[0] for d in data])

        if not text:
            text = "No projects"

        return await query.edit_message_text(
            f"📂 Your Projects:\n\n{text}"
        )

    if query.data == "mydel":

        USER_DELETE_MODE.add(chat_id)

        return await query.edit_message_text(
            "Send the project name to delete:"
        )

    if query.data == "myclear":

        cursor.execute(
            "DELETE FROM reminders WHERE user_id=?",
            (chat_id,)
        )

        conn.commit()

        return await query.edit_message_text(
            "🧹 Your data cleared"
        )

    # ---------------- ADMIN CHECK ----------------
    if chat_id not in ADMIN_USERS:
        return await query.edit_message_text("❌ Not authorized")

    # ---------------- VIEW DB ----------------
    if query.data == "db":

        cursor.execute("SELECT * FROM reminders")
        data = cursor.fetchall()

        if not data:
            return await query.edit_message_text("Database empty")

        text = ""

        for row in data:
            text += (
                f"ID: {row[0]}\n"
                f"USER: {row[1]}\n"
                f"PROJECT: {row[2]}\n"
                f"DATE: {row[4]}\n\n"
            )

        return await query.edit_message_text(text[:4000])

    # ---------------- VIEW PROJECTS ----------------
    if query.data == "projects":

        cursor.execute("SELECT DISTINCT project FROM reminders")
        data = cursor.fetchall()

        text = "\n".join([d[0] for d in data])

        if not text:
            text = "No projects"

        return await query.edit_message_text(
            f"📂 Projects:\n\n{text}"
        )

    # ---------------- ADMIN DELETE ----------------
    if query.data == "adel":

        cursor.execute("SELECT DISTINCT project FROM reminders")
        data = cursor.fetchall()

        text = "\n".join([d[0] for d in data])

        if not text:
            text = "No projects"

        ADMIN_DELETE_MODE.add(chat_id)

        return await query.edit_message_text(
            f"Send project name to delete:\n\n{text}"
        )

    # ---------------- CLEAR DB ----------------
    if query.data == "clear":

        cursor.execute("SELECT DISTINCT user_id FROM reminders")
        users = cursor.fetchall()

        cursor.execute("DELETE FROM reminders")
        conn.commit()

        for u in users:
            try:
                await context.bot.send_message(
                    chat_id=u[0],
                    text="⚠️ All your data was cleared by admin"
                )
            except:
                pass

        return await query.edit_message_text("🧹 Database cleared")

# ---------------- MAIN ----------------
def main():

    print("Bot running...")

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("input", input_cmd))
    app.add_handler(CommandHandler("user", user_panel))
    app.add_handler(CommandHandler("admin", admin))

    app.add_handler(CallbackQueryHandler(buttons))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    app.run_polling()

# ---------------- START ----------------
if __name__ == "__main__":
    main()
