import os
import re
import sqlite3
import logging
import asyncio
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
    notified_2d INTEGER DEFAULT 0
)
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

# ---------------- GET ----------------
def get_all_tasks():
    cursor.execute("SELECT id, user_id, project, date, notified_3d, notified_2d FROM reminders")
    return cursor.fetchall()

# ---------------- DELETE ----------------
def delete_task(task_id):
    cursor.execute("DELETE FROM reminders WHERE id=?", (task_id,))
    conn.commit()

# ---------------- USER PROJECTS ----------------
def get_user_projects(user_id):
    cursor.execute("SELECT DISTINCT project FROM reminders WHERE user_id=?", (user_id,))
    return cursor.fetchall()

# ---------------- INPUT ----------------
async def input_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    INPUT_MODE.add(update.effective_chat.id)

    await update.message.reply_text(
        "Project name: YOUR_PROJECT\nDelivery date: 26 May 2026"
    )

# ---------------- MESSAGE ----------------
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    text = update.message.text.strip()

    if chat_id in INPUT_MODE:
        match = re.search(r"Project name:\s*(.+)\s+Delivery date:\s*(.+)", text, re.IGNORECASE)

        if not match:
            return await update.message.reply_text("❌ Wrong format")

        project = match.group(1).strip().lower()
        date_text = match.group(2).strip()

        date = parse_date(date_text)

        if not date:
            return await update.message.reply_text("❌ Invalid date")

        save(chat_id, project, date.strftime("%Y-%m-%d"))

        INPUT_MODE.remove(chat_id)
        return await update.message.reply_text("✅ Saved successfully!")

# ---------------- REMINDER ENGINE ----------------
async def reminder_checker(app):
    while True:
        try:
            tasks = get_all_tasks()
            now = datetime.now().date()

            for task in tasks:
                task_id, user_id, project, date_str, n3, n2 = task

                try:
                    due = datetime.strptime(date_str, "%Y-%m-%d").date()
                except:
                    continue

                diff = (due - now).days

                # ---------------- 3 DAYS REMINDER ----------------
                if diff == 3 and not n3:
                    await app.bot.send_message(
                        chat_id=user_id,
                        text=f"⏰ Reminder: '{project}' due in 3 days!"
                    )
                    cursor.execute("UPDATE reminders SET notified_3d=1 WHERE id=?", (task_id,))
                    conn.commit()

                # ---------------- 2 DAYS REMINDER ----------------
                if diff == 2 and not n2:
                    await app.bot.send_message(
                        chat_id=user_id,
                        text=f"⚠️ Reminder: '{project}' due in 2 days!"
                    )
                    cursor.execute("UPDATE reminders SET notified_2d=1 WHERE id=?", (task_id,))
                    conn.commit()

                # ---------------- EXPIRED AUTO DELETE ----------------
                if diff < 0:
                    await app.bot.send_message(
                        chat_id=user_id,
                        text=f"❌ '{project}' expired and removed automatically"
                    )
                    delete_task(task_id)

        except Exception as e:
            print("Reminder error:", e)

        await asyncio.sleep(10800)  # 3 hours

# ---------------- ADMIN ----------------
async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or context.args[0] != ADMIN_CODE:
        return await update.message.reply_text("❌ Wrong code")

    ADMIN_USERS.add(update.effective_chat.id)

    keyboard = [
        [InlineKeyboardButton("📂 View Projects", callback_data="projects")]
    ]

    await update.message.reply_text(
        "👑 Admin Panel",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ---------------- BUTTONS ----------------
async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "projects":
        cursor.execute("SELECT DISTINCT project FROM reminders")
        data = cursor.fetchall()

        text = "\n".join([d[0] for d in data]) or "No projects"

        return await query.edit_message_text(text)

# ---------------- MAIN ----------------
def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("input", input_cmd))
    app.add_handler(CommandHandler("admin", admin))

    app.add_handler(CallbackQueryHandler(buttons))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # background reminder task
    app.job_queue.run_repeating(lambda ctx: asyncio.create_task(reminder_checker(app)), interval=10800, first=10)

    print("Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()
