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

# ---------------- CONFIG ----------------
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CODE = "13465"

ADMIN_USERS = set()
INPUT_MODE = set()

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
    notified_3d INTEGER DEFAULT 0,
    notified_2d INTEGER DEFAULT 0,
    deleted INTEGER DEFAULT 0
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

# =========================================================
# ⏰ AUTO REMINDER SYSTEM (NEW FEATURE)
# =========================================================

async def auto_checker(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now()

    cursor.execute("SELECT id, user_id, project, date, notified_3d, notified_2d FROM reminders")
    rows = cursor.fetchall()

    for r in rows:
        rid, uid, project, date_str, n3, n2 = r

        try:
            due = datetime.strptime(date_str, "%Y-%m-%d")
        except:
            continue

        diff = (due - now).days

        # ---------------- 3 DAYS REMINDER ----------------
        if diff <= 3 and n3 == 0:
            try:
                await context.bot.send_message(
                    chat_id=uid,
                    text=f"⏰ Reminder: '{project}' is due in 3 days"
                )
            except:
                pass

            cursor.execute(
                "UPDATE reminders SET notified_3d=1 WHERE id=?",
                (rid,)
            )
            conn.commit()

        # ---------------- 2 DAYS REMINDER ----------------
        if diff <= 2 and n2 == 0:
            try:
                await context.bot.send_message(
                    chat_id=uid,
                    text=f"⚠️ Reminder: '{project}' is due in 2 days"
                )
            except:
                pass

            cursor.execute(
                "UPDATE reminders SET notified_2d=1 WHERE id=?",
                (rid,)
            )
            conn.commit()

        # ---------------- EXPIRED AUTO DELETE ----------------
        if diff < 0:
            try:
                await context.bot.send_message(
                    chat_id=uid,
                    text=f"🗑 Your project '{project}' is expired and deleted automatically"
                )
            except:
                pass

            cursor.execute("DELETE FROM reminders WHERE id=?", (rid,))
            conn.commit()

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

# ---------------- MESSAGE HANDLER ----------------
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):

    chat_id = update.effective_chat.id
    text = update.message.text.strip()

    if chat_id in INPUT_MODE:

        match = re.search(
            r"Project name:\s*(.+)\s+Delivery date:\s*(.+)",
            text,
            re.IGNORECASE
        )

        if not match:
            return await update.message.reply_text("❌ Wrong format")

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

    if chat_id in USER_DELETE_MODE:

        project = text.strip().lower()
        deleted = delete_user_project(chat_id, project)

        USER_DELETE_MODE.remove(chat_id)

        if deleted == 0:
            return await update.message.reply_text("❌ Project not found")

        return await update.message.reply_text(f"🗑 Deleted: {project}")

    if chat_id in ADMIN_DELETE_MODE:

        project = text.strip().lower()
        users = admin_delete_project(project)

        ADMIN_DELETE_MODE.remove(chat_id)

        if not users:
            return await update.message.reply_text("❌ Project not found")

        for user_id in users:
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"❌ Your project '{project}' was deleted by admin"
                )
            except:
                pass

        return await update.message.reply_text(f"🗑 Admin deleted: {project}")

# ---------------- BUTTONS ----------------
async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    chat_id = query.message.chat_id

    if query.data == "my":
        data = get_user_projects(chat_id)
        text = "\n".join([d[0] for d in data]) or "No projects"
        return await query.edit_message_text(text)

    if query.data == "mydel":
        USER_DELETE_MODE.add(chat_id)
        return await query.edit_message_text("Send project name to delete:")

    if query.data == "myclear":
        cursor.execute("DELETE FROM reminders WHERE user_id=?", (chat_id,))
        conn.commit()
        return await query.edit_message_text("🧹 Cleared")

    if chat_id not in ADMIN_USERS:
        return await query.edit_message_text("❌ Not authorized")

    if query.data == "db":
        cursor.execute("SELECT * FROM reminders")
        return await query.edit_message_text(str(cursor.fetchall()))

    if query.data == "projects":
        cursor.execute("SELECT DISTINCT project FROM reminders")
        data = cursor.fetchall()
        text = "\n".join([d[0] for d in data])
        return await query.edit_message_text(text or "No projects")

    if query.data == "adel":
        cursor.execute("SELECT DISTINCT project FROM reminders")
        data = cursor.fetchall()
        text = "\n".join([d[0] for d in data])
        ADMIN_DELETE_MODE.add(chat_id)
        return await query.edit_message_text("Send project name:\n\n" + text)

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

        return await query.edit_message_text("🧹 DB cleared")

# ---------------- MAIN ----------------
def main():

    app = Application.builder().token(TOKEN).build()

    # 🔥 AUTO CHECK EVERY 3 HOURS
    app.job_queue.run_repeating(auto_checker, interval=10800, first=10)

    app.add_handler(CommandHandler("input", input_cmd))
    app.add_handler(CommandHandler("user", user_panel))
    app.add_handler(CommandHandler("admin", admin))

    app.add_handler(CallbackQueryHandler(buttons))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    app.run_polling()

if __name__ == "__main__":
    main()
