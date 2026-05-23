import os
import re
import sqlite3
import logging
import asyncio
from datetime import datetime, date

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

# reminder tracking columns
try:
    cursor.execute("ALTER TABLE reminders ADD COLUMN notified_3d INTEGER DEFAULT 0")
except:
    pass

try:
    cursor.execute("ALTER TABLE reminders ADD COLUMN notified_2d INTEGER DEFAULT 0")
except:
    pass

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
    cursor.execute("SELECT DISTINCT project FROM reminders WHERE user_id=?", (user_id,))
    return cursor.fetchall()

# ---------------- DELETE ----------------
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

def admin_delete_project(project):
    project = project.strip().lower()

    cursor.execute("SELECT DISTINCT user_id FROM reminders WHERE project=?", (project,))
    users = cursor.fetchall()

    if not users:
        return []

    cursor.execute("DELETE FROM reminders WHERE project=?", (project,))
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

        match = re.search(r"Project name:\s*(.+)\s+Delivery date:\s*(.+)", text)

        if not match:
            return await update.message.reply_text("❌ Wrong format")

        project = match.group(1).lower().strip()
        date_text = match.group(2).strip()

        d = parse_date(date_text)

        if not d:
            return await update.message.reply_text("❌ Invalid date")

        ok = save(chat_id, project, d.strftime("%Y-%m-%d"))

        INPUT_MODE.remove(chat_id)

        return await update.message.reply_text(
            "✅ Saved!" if ok else "⚠️ Duplicate ignored!"
        )

    if chat_id in USER_DELETE_MODE:
        project = text.lower().strip()
        delete_user_project(chat_id, project)
        USER_DELETE_MODE.remove(chat_id)
        return await update.message.reply_text("🗑 Deleted")

    if chat_id in ADMIN_DELETE_MODE:
        project = text.lower().strip()
        users = admin_delete_project(project)

        ADMIN_DELETE_MODE.remove(chat_id)

        for u in users:
            try:
                await context.bot.send_message(u, f"❌ {project} deleted by admin")
            except:
                pass

        return await update.message.reply_text("🗑 Deleted")

    await update.message.reply_text("❌ Wrong input\nUse /input /user /admin")

# ---------------- BUTTONS ----------------
async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):

    q = update.callback_query
    await q.answer()

    chat_id = q.message.chat_id

    if q.data == "my":
        data = get_user_projects(chat_id)
        text = "\n".join([d[0] for d in data]) or "No projects"
        return await q.edit_message_text(text)

    if q.data == "mydel":
        USER_DELETE_MODE.add(chat_id)
        return await q.edit_message_text("Send project name")

    if q.data == "myclear":
        cursor.execute("DELETE FROM reminders WHERE user_id=?", (chat_id,))
        conn.commit()
        return await q.edit_message_text("Cleared")

    if chat_id not in ADMIN_USERS:
        return await q.edit_message_text("❌ Not authorized")

    if q.data == "db":
        cursor.execute("SELECT * FROM reminders LIMIT 10")
        return await q.edit_message_text(str(cursor.fetchall()))

    if q.data == "projects":
        cursor.execute("SELECT DISTINCT project FROM reminders")
        data = cursor.fetchall()
        text = "\n".join([d[0] for d in data]) or "No projects"
        return await q.edit_message_text(text)

    if q.data == "adel":
        ADMIN_DELETE_MODE.add(chat_id)
        return await q.edit_message_text("Send project name")

    if q.data == "clear":
        cursor.execute("DELETE FROM reminders")
        conn.commit()
        return await q.edit_message_text("DB cleared")

# ---------------- REMINDER ENGINE ----------------
async def reminder_engine(app):

    while True:
        try:
            cursor.execute("SELECT id, user_id, project, date, notified_3d, notified_2d FROM reminders")
            rows = cursor.fetchall()

            today = date.today()

            for r in rows:
                rid, uid, project, d, n3, n2 = r

                try:
                    due = datetime.strptime(d, "%Y-%m-%d").date()
                except:
                    continue

                diff = (due - today).days

                if diff == 3 and n3 == 0:
                    await app.bot.send_message(uid, f"⏰ {project} due in 3 days")
                    cursor.execute("UPDATE reminders SET notified_3d=1 WHERE id=?", (rid,))
                    conn.commit()

                if diff == 2 and n2 == 0:
                    await app.bot.send_message(uid, f"⚠️ {project} due in 2 days")
                    cursor.execute("UPDATE reminders SET notified_2d=1 WHERE id=?", (rid,))
                    conn.commit()

                if diff < 0:
                    await app.bot.send_message(uid, f"❌ {project} expired & deleted")
                    cursor.execute("DELETE FROM reminders WHERE id=?", (rid,))
                    conn.commit()

        except Exception as e:
            print("Reminder error:", e)

        await asyncio.sleep(10800)  # 3 hours

# ---------------- STARTUP FIX ----------------
async def post_init(app: Application):
    app.create_task(reminder_engine(app))

# ---------------- MAIN ----------------
def main():

    app = Application.builder().token(TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("input", input_cmd))
    app.add_handler(CommandHandler("user", user_panel))
    app.add_handler(CommandHandler("admin", admin))

    app.add_handler(CallbackQueryHandler(buttons))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()
