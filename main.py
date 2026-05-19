from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
from datetime import datetime
import sqlite3
import re
import logging

# ---------------- LOGGING ----------------
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

# ---------------- TOKEN (Render a ENV theke nibe) ----------------
import os
TOKEN = os.getenv("BOT_TOKEN")

# ---------------- DATABASE ----------------
conn = sqlite3.connect("reminders.db", check_same_thread=False, timeout=10)
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

# ---------------- DATE PARSE ----------------
def extract_date(text):
    patterns = [
        r"(\d{1,2} \w+ \d{4})",
        r"(\d{4}-\d{2}-\d{2})"
    ]

    for p in patterns:
        match = re.search(p, text)
        if match:
            try:
                return datetime.strptime(match.group(1), "%d %B %Y")
            except:
                try:
                    return datetime.strptime(match.group(1), "%Y-%m-%d")
                except:
                    pass
    return None

# ---------------- SAVE ----------------
def save_reminder(text, date, chat_id):
    cursor.execute(
        "SELECT id FROM reminders WHERE text=? AND date=? AND chat_id=?",
        (text, date.strftime("%Y-%m-%d"), chat_id)
    )
    if cursor.fetchone():
        return

    cursor.execute(
        "INSERT INTO reminders (text, date, chat_id) VALUES (?, ?, ?)",
        (text, date.strftime("%Y-%m-%d"), chat_id)
    )
    conn.commit()

# ---------------- GET ----------------
def get_reminders():
    cursor.execute("SELECT id, text, date, chat_id, phase FROM reminders")
    rows = cursor.fetchall()

    return [
        {
            "id": r[0],
            "text": r[1],
            "date": datetime.strptime(r[2], "%Y-%m-%d"),
            "chat_id": r[3],
            "phase": r[4]
        }
        for r in rows
    ]

# ---------------- MESSAGE HANDLER ----------------
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    text = update.message.text
    chat_id = update.effective_chat.id
    date = extract_date(text)

    if date:
        save_reminder(text, date, chat_id)

        await context.bot.send_message(
            chat_id=chat_id,
            text="✅ Saved!\n⏰ Reminder activated."
        )

# ---------------- REMINDER CHECK ----------------
async def check_reminders(context: ContextTypes.DEFAULT_TYPE):
    try:
        now = datetime.now().date()
        reminders = get_reminders()

        for r in reminders:
            diff = (r["date"].date() - now).days

            if diff == 3 and r["phase"] != "3d":
                cursor.execute("UPDATE reminders SET phase='3d' WHERE id=?", (r["id"],))
                conn.commit()

                await context.bot.send_message(
                    chat_id=r["chat_id"],
                    text=f"📢 3 DAYS LEFT\n\n{r['text']}"
                )

            elif diff == 2 and r["phase"] != "2d":
                cursor.execute("UPDATE reminders SET phase='2d' WHERE id=?", (r["id"],))
                conn.commit()

                await context.bot.send_message(
                    chat_id=r["chat_id"],
                    text=f"⚠️ 2 DAYS LEFT\n\n{r['text']}"
                )

            elif diff < 0:
                await context.bot.send_message(
                    chat_id=r["chat_id"],
                    text=f"❌ DEADLINE OVER\nAuto removed\n\n{r['text']}"
                )

                cursor.execute("DELETE FROM reminders WHERE id=?", (r["id"],))
                conn.commit()

    except Exception as e:
        print("Error:", e)

# ---------------- JOB START ----------------
def start_jobs(app):
    app.job_queue.run_repeating(check_reminders, interval=10800, first=10)

# ---------------- MAIN ----------------
def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )

    start_jobs(app)

    print("Bot running...")
    app.run_polling()

# ---------------- START ----------------
if __name__ == "__main__":
    main()
