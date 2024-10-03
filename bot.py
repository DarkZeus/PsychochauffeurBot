import asyncio
import os
import re
import logging
import httpx  # Used for Discord integration, should be verified in case of issues
import nest_asyncio
import datetime
import random
import imgkit  # Ensure imgkit is configured correctly on your server
import pytz
import requests

from telegram import Update, ChatPermissions
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, CallbackContext
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Apply nest_asyncio to handle nested event loops
nest_asyncio.apply()

# Your OpenWeatherMap API key
OPENWEATHER_API_KEY = os.getenv('OPENWEATHER_API_KEY')

# Discord Webhook URL from environment variables
DISCORD_WEBHOOK_URL = os.getenv('DISCORD_WEBHOOK_URL')

# Set the base directory for screenshots
SCREENSHOT_DIR = 'python-web-screenshots'

# Telegram Bot Token from environment variables
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')

# Set up logging for debugging; consider using a file handler for persistent logs
logging.basicConfig(level=logging.INFO)

async def start(update: Update, context: CallbackContext):
    logging.debug("Received /start command.")
    await update.message.reply_text("Hello! Send me TikTok, Twitter, or Instagram links, and I will modify them for you!")

# Utility function to remove all URLs from a given text
def remove_links(text):
    return re.sub(r'http[s]?://\S+', '', text).strip()

# Utility function to check if a given string is a URL
def is_url(string: str) -> bool:
    url_pattern = re.compile(r'http[s]?://\S+')
    return bool(url_pattern.match(string))

# Dictionary to map Ukrainian city names to English names (used by OpenWeatherMap)
city_translations = {
    "Кортгене": "Kortgene",
    "кортгене": "Kortgene",
    "Тель Авів": "Tel Aviv",
    "тель Авів": "Tel Aviv",
    "Тель авів": "Tel Aviv",
    "тель авів": "Tel Aviv",
    # Add other cities as needed
}

# Function to fetch weather data from OpenWeatherMap
async def get_weather(city: str) -> str:

    # Check if the Ukrainian city name exists in the translation dictionary
    city = city_translations.get(city, city).lower()  # If no translation is found, use the original input

    base_url = "http://api.openweathermap.org/data/2.5/weather"
    params = {
        "q": city,
        "appid": OPENWEATHER_API_KEY,
        "units": "metric",  # You can change to 'imperial' if needed
        "lang": "uk"  # Setting language to Ukrainian
    }
    
    try:
        response = requests.get(base_url, params=params)
        data = response.json()
        
        if data["cod"] != 200:
            return f"Error: {data['message']}"

        # Parse the weather data
        city_name = data["name"]
        weather_description = data["weather"][0]["description"]
        temp = data["main"]["temp"]
        feels_like = data["main"]["feels_like"]
        
        return (f"Погода у {city_name}:\n"
                f"{weather_description.capitalize()}\n"
                f"Температура: {temp}°C\n"
                f"Відчувається як: {feels_like}°C")
    except Exception as e:
        return f"Не вдалося отримати дані про погоду: {str(e)}"


# Main message handler function
async def handle_message(update: Update, context: CallbackContext):
    if update.message and update.message.text:
        message_text = update.message.text
        chat_id = update.message.chat_id
        username = update.message.from_user.username
        message_id = update.message.message_id

        logging.debug(f"Processing message: {message_text}")

        # Check for trigger words in the message
        if any(trigger in message_text for trigger in ["5€", "€5", "5 євро", "5 єуро", "5 €", "Ы", "ы", "ъ", "Ъ", "Э", "э", "Ё", "ё"]):
            await restrict_user(update, context)
            return  # Exit after handling this specific case

        # Initialize modified_links list
        modified_links = []

        # Check for specific domain links and modify them
        if any(domain in message_text for domain in ["tiktok.com", "twitter.com", "x.com", "instagram.com"]):
            links = message_text.split()
            for link in links:
                if is_url(link):
                    if "vm.tiktok.com" in link or "tiktok.com" in link:
                        modified_link = link.replace("tiktok.com", "tfxktok.com")
                    elif "twitter.com" in link or "x.com" in link:
                        modified_link = link.replace("twitter.com", "fxtwitter.com").replace("x.com", "fixupx.com")
                    elif "instagram.com" in link:
                        modified_link = link.replace("instagram.com", "ddinstagram.com")
                    else:
                        modified_link = link

                    modified_links.append(modified_link)

        # If there are modified links, send the modified message
        if modified_links:
            cleaned_message_text = remove_links(message_text)
            modified_message = "\n".join(modified_links)
            final_message = f"@{username}💬: {cleaned_message_text}\n\nModified links:\n{modified_message}"
            await context.bot.send_message(chat_id=chat_id, text=final_message)
            logging.debug(f"Sent message: {final_message}")

            # Delete the original message
            await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
            logging.debug("Deleted original message.")




async def restrict_user(update: Update, context: CallbackContext):
    chat = update.effective_chat
    user_id = update.message.from_user.id
    username = update.message.from_user.username  # Get the username for the reply message

    # Check if the user is the chat owner or an admin
    chat_member = await context.bot.get_chat_member(chat.id, user_id)
    if chat_member.status in ["administrator", "creator"]:
        logging.info("You cannot restrict an admin or the chat owner.")
        return

    if chat.type == "supergroup":
        try:
            restrict_duration = random.randint(1, 5)  # Restriction duration in minutes
            permissions = ChatPermissions(can_send_messages=False)

            # Get current time in EEST
            eest_now = datetime.datetime.now(pytz.timezone('Europe/Helsinki'))
            until_date = eest_now + datetime.timedelta(minutes=restrict_duration)

            # Restrict user in the chat
            await context.bot.restrict_chat_member(
                chat_id=chat.id,
                user_id=user_id,
                permissions=permissions,
                until_date=until_date
            )

            # Notify user with a custom sticker
            sticker_id = "CAACAgQAAxkBAAEt8tNm9Wc6jYEQdAgQzvC917u3e8EKPgAC9hQAAtMUCVP4rJSNEWepBzYE"
            await update.message.reply_text(f"Вас запсихопаркували на {restrict_duration} хвилин. Ви не можете надсилати повідомлення.")
            await context.bot.send_sticker(chat_id=chat.id, sticker=sticker_id)

        except Exception as e:
            logging.error(f"Failed to restrict user: {e}")
    else:
        await update.message.reply_text("This command is only available in supergroups.")

async def handle_sticker(update: Update, context: CallbackContext):
    # Get unique ID of the sticker
    sticker_id = update.message.sticker.file_unique_id
    username = update.message.from_user.username  # Getting the sender's username

    logging.debug(f"Received sticker with file_unique_id: {sticker_id}")

    # Check if the sticker ID matches the specific stickers you want to react to
    if sticker_id == "AgAD6BQAAh-z-FM":  # Replace with your actual unique sticker ID
        logging.info(f"Matched specific sticker from {username}, restricting user.")
        await restrict_user(update, context)
    else:
        logging.info(f"Sticker ID {sticker_id} does not match the trigger sticker.")



# Handler to check messages for YouTube links and send them to Discord
async def check_message_for_links(update: Update, context: CallbackContext):
    message_text = update.message.text
    youtube_regex = r'(https?://(?:www\.)?youtube\.com/[\w\-\?&=]+)'

    logging.debug(f"Checking for YouTube links in message: {message_text}")

    youtube_links = re.findall(youtube_regex, message_text)

    if youtube_links:
        for link in youtube_links:
            await send_to_discord(link)


# Command handler for /weather <city>
async def weather(update: Update, context: CallbackContext):
    if context.args:
        city = " ".join(context.args)
        weather_info = await get_weather(city)
        if update.message:
            await update.message.reply_text(weather_info)
    else:
        await update.message.reply_text("Будь ласка, вкажіть назву міста.")


# Function to send messages to Discord
async def send_to_discord(message: str):
    payload = {"content": message}
    try:
        # Use an HTTP client to send the message to Discord
        async with httpx.AsyncClient() as client:
            response = await client.post(DISCORD_WEBHOOK_URL, json=payload)
            response.raise_for_status()
            logging.info(f"Message sent to Discord: {response.text}")
    except Exception as e:
        logging.error(f"Error sending to Discord: {e}")

# Screenshot command to capture the current state of a webpage
async def screenshot_command(update: Update, context: CallbackContext):
    screenshot_path = take_screenshot()

    if screenshot_path:
        chat_id = update.effective_chat.id
        with open(screenshot_path, 'rb') as photo:
            await context.bot.send_photo(chat_id=chat_id, photo=photo)
    else:
        await update.message.reply_text("Failed to take screenshot. Please try again later.")

def take_screenshot():
    # Add 3 hours to current time to match the update at 0 UTC
    adjusted_time = datetime.datetime.now() + datetime.timedelta(hours=-3)
    date_str = adjusted_time.strftime('%Y-%m-%d')
    screenshot_path = os.path.join(SCREENSHOT_DIR, f'flares_{date_str}.png')

    # Check if the screenshot for the adjusted date already exists
    if os.path.exists(screenshot_path):
        logging.info(f"Screenshot for today already exists: {screenshot_path}")
        return screenshot_path

    config = imgkit.config(wkhtmltoimage='/usr/bin/wkhtmltoimage')

    try:
        # Capture the screenshot of the desired webpage
        imgkit.from_url('https://api.meteoagent.com/widgets/v1/kindex', screenshot_path, config=config)
        logging.info(f"Screenshot taken and saved to: {screenshot_path}")
        return screenshot_path
    except Exception as e:
        logging.error(f"Error taking screenshot: {e}")
        return None



# Main function to initialize and run the bot
async def main():
    try:
        application = ApplicationBuilder().token(TOKEN).build()
        logging.debug("Application initialized.")

        # Add handlers
        application.add_handler(CommandHandler('start', start))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, check_message_for_links))
        application.add_handler(CommandHandler('flares', screenshot_command))

        # Add sticker handler to detect stickers
        application.add_handler(MessageHandler(filters.Sticker.ALL, handle_sticker))  # Add this line for stickers

        weather_handler = CommandHandler("weather", weather)
        application.add_handler(weather_handler)
        

        # Start the bot
        await application.run_polling()
    finally:
        await application.shutdown()

# Function to run the bot, handles event loop issues
def run_bot():
    loop = asyncio.get_event_loop()
    if loop.is_running():
        task = loop.create_task(main())
        return task
    else:
        asyncio.run(main())

if __name__ == '__main__':
    try:
        run_bot()
    except RuntimeError as e:
        logging.error(f"RuntimeError occurred: {e}")
    except Exception as e:
        logging.error(f"An error occurred: {e}")

