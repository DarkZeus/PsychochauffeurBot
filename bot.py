import asyncio
import hashlib
import logging
import nest_asyncio
import pytz
import random

from modules.keyboards import create_link_keyboard, button_callback
from utils import remove_links, screenshot_command, schedule_task, cat_command, ScreenshotManager, game_state, game_command, end_game_command, clear_words_command, hint_command, load_game_state
from const import domain_modifications, TOKEN, ALIEXPRESS_STICKER_ID
from modules.gpt import ask_gpt_command, analyze_command, answer_from_gpt
from modules.weather import weather
from modules.file_manager import general_logger, chat_logger
from modules.user_management import restrict_user
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, CallbackContext, \
    CallbackQueryHandler

# Apply the patch to allow nested event loops
nest_asyncio.apply()
LOCAL_TZ = pytz.timezone('Europe/Kyiv')

message_counts = {}


def contains_trigger_words(message_text):
    triggers = ["5€", "€5", "5 євро", "5 єуро", "5 €", "Ы", "ы", "ъ", "Ъ", "Э", "э", "Ё", "ё"]
    return any(trigger in message_text for trigger in triggers)

async def start(update: Update, context: CallbackContext):
    general_logger.info(f"Processing /start command from user {update.message.from_user.id} in chat {update.effective_chat.id}")
    await update.message.reply_text("Hello! Send me TikTok, Twitter, or Instagram links, and I will modify them for you!")

async def handle_message(update: Update, context: CallbackContext):
    if not update.message or not update.message.text:
        return

    message_text = update.message.text
    chat_id = update.message.chat_id
    username = update.message.from_user.username
    chat_title = update.message.chat.title if update.message.chat.title else "Private Chat"

    # Log message with extra fields
    chat_logger.info(f"User message: {message_text}", extra={'chat_id': chat_id, 'chattitle': chat_title, 'username': username})

    # Check message conditions
    is_private_chat = update.effective_chat.type == 'private'
    is_mention = context.bot.username in message_text
    is_reply = update.message.reply_to_message is not None

    # Handle trigger words
    if contains_trigger_words(message_text):
        await restrict_user(update, context)
        return

    # Handle AliExpress links
    if any(domain in message_text for domain in ["aliexpress.com/item/", "a.aliexpress.com/"]):
        await update.message.reply_sticker(sticker=ALIEXPRESS_STICKER_ID)

    # Handle domain modifications
    modified_links = []
    original_links = []
    for link in message_text.split():
        # Skip links that are already modified
        if any(modified_domain in link for modified_domain in domain_modifications.values()):
            continue

        # Modify unmodified links
        for domain, modified_domain in domain_modifications.items():
            if domain in link:
                modified_link = link.replace(domain, modified_domain)
                modified_links.append(modified_link)
                original_links.append(modified_link)
                break

    if modified_links:
        try:
            # Create the message
            cleaned_message_text = remove_links(message_text)
            modified_message = "\n".join(modified_links)
            final_message = f"@{username}💬: {cleaned_message_text}\n\nModified links:\n{modified_message}"

            # Store the link and create keyboard
            link_hash = hashlib.md5(modified_links[0].encode()).hexdigest()[:8]
            context.bot_data[link_hash] = modified_links[0]
            reply_markup = create_link_keyboard(modified_links[0])

            # Send modified message and delete original
            await context.bot.send_message(
                chat_id=chat_id,
                text=final_message,
                reply_to_message_id=update.message.reply_to_message.message_id if update.message.reply_to_message else None,
                reply_markup=reply_markup
            )
            await context.bot.delete_message(chat_id=chat_id, message_id=update.message.message_id)

        except Exception as e:
            general_logger.error(f"Error modifying links: {str(e)}")
            await update.message.reply_text("Sorry, an error occurred. Please try again.")

    # Handle GPT queries
    if is_mention or is_private_chat:
        # Check if this is a reply to a modified link message
        if is_reply and update.message.reply_to_message.text:
            # Check if the replied message contains "Modified links:"
            if "Modified links:" in update.message.reply_to_message.text:
                return  # Skip GPT processing for replies to modified links
        cleaned_message = message_text.replace(f"@{context.bot.username}", "").strip()
        cleaned_message = update.message.text  # Assuming this is how you get the message
        await ask_gpt_command(cleaned_message, update, context)

    # Call the random GPT response function
    await random_gpt_response(update, context)


async def random_gpt_response(update: Update, context: CallbackContext):
    """Randomly responds to a message with a 2% chance using GPT, only if the message has 5 or more words."""
    chat_id = update.message.chat_id
    message_counts[chat_id] = message_counts.get(chat_id, 0) + 1

    message_text = update.message.text
    word_count = len(message_text.split())  # Count the number of words

    if word_count < 5:  # Check if the message has less than 5 words
        return  # Skip processing if not enough words

    if random.random() < 0.02 and message_counts[chat_id] > 40:
        general_logger.info(f"Random GPT response triggered in chat {chat_id}: {message_text}")
        
        # Call the GPT function
        await answer_from_gpt(message_text, update, context)
        
        # Reset message count for the chat
        message_counts[chat_id] = 0

async def handle_sticker(update: Update, context: CallbackContext):
    sticker_id = update.message.sticker.file_unique_id
    username = update.message.from_user.username
    
    general_logger.info(f"Received sticker with file_unique_id: {sticker_id}")
    
    if sticker_id == "AgAD6BQAAh-z-FM":
        logging.info(f"Matched specific sticker from {username}, restricting user.")
        await restrict_user(update, context)

async def main():
    # Load game state at startup
    load_game_state()
    
    bot = ApplicationBuilder().token(TOKEN).build()
    
    # Add command handlers
    commands = {
        'start': start,
        'cat': cat_command,
        'gpt': ask_gpt_command,
        'analyze': analyze_command,
        'flares': screenshot_command,
        'weather': weather,
        'game': game_command,
        'endgame': end_game_command,
        'clearwords': clear_words_command,
        'hint': hint_command  # Add hint command
    }
    
    for command, handler in commands.items():
        bot.add_handler(CommandHandler(command, handler))

    # Add message handlers
    bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    bot.add_handler(MessageHandler(filters.Sticker.ALL, handle_sticker))
    bot.add_handler(CallbackQueryHandler(button_callback))

    # Start the screenshot scheduler
    screenshot_manager = ScreenshotManager()  # Create instance first
    asyncio.create_task(screenshot_manager.schedule_task())

    # Start bot
    await bot.run_polling()
    await bot.idle()

if __name__ == '__main__':
    new_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(new_loop)
    new_loop.run_until_complete(main())
