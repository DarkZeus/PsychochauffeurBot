import openai
import logging
# import os

from modules.file_manager import general_logger, chat_logger, read_last_n_lines
from const import OPENAI_API_KEY


# Load the OpenAI API key from environment variables
# OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')

from telegram import Update
from telegram.ext import CallbackContext, ContextTypes
from openai import AsyncClient


# aclient = AsyncOpenAI(api_key=OPENAI_API_KEY)
client = AsyncClient(api_key=OPENAI_API_KEY)
openai.api_key = OPENAI_API_KEY




async def ask_gpt_command(update: Update, context: CallbackContext):
    """Handles the /gpt command to query GPT with a question."""
    if not context.args:
        await update.message.reply_text("Please provide a question, e.g., /gpt What is the weather?")
        return

    question = " ".join(context.args)
    try:
        # Send the question to GPT
        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "system", "content": (
                    "If the user's request appears to be in Russian, respond in Ukrainian instead. "
                    "Do not reply in Russian in any circumstance."
                )},
                {"role": "user", "content": question}
            ],
            max_tokens=750,
            temperature=0.7
        )

        # Extract GPT's response
        gpt_reply = response.choices[0].message.content
        await update.message.reply_text(gpt_reply)

        # Log the interaction
        chat_title = update.message.chat.title if update.message.chat.title else "Private Chat"
        user_name = update.message.from_user.username if update.message.from_user.username else "Unknown User"
        chat_id = update.message.chat_id if update.message.chat_id else "Unknown chat"
        chat_logger.info(f"User {update.message.from_user.username} asked GPT: {question}", extra={'chattitle': chat_title, 'username': user_name, 'chat_id': chat_id})
        chat_logger.info(f"GPT's response: {gpt_reply}", extra={'chattitle': chat_title, 'username': user_name, 'chat_id': chat_id})

    except Exception as e:
        general_logger.error(f"Failed to communicate with GPT: {e}")
        await update.message.reply_text("Sorry, I couldn't get an answer right now.")


async def gpt_summary_function(messages):
    try:
        # Join the messages into a single string
        messages_text = "\n".join(messages)

        # Create the prompt for GPT
        prompt = f"Підсумуйте наступні повідомлення:\n\n{messages_text}\n\nПідсумок:"

        # Call the OpenAI API to get the summary
        response = await client.chat.completions.create(  # Ensure this matches your library's documentation
            model="gpt-4o-mini",  # or any other model you prefer
            messages=[
                {"role": "user", "content": prompt}
            ],
            max_tokens=750,  # Adjust the number of tokens for the summary as needed
            temperature=0.7  # Adjust the creativity of the response
        )

        # Extract the summary from the response
        summary = response.choices[0].message.content.strip()  # Adjust based on actual response structure
        return summary
    except Exception as e:
        logging.error(f"Error in GPT summarization: {e}")
        return "Не вдалося згенерувати підсумок."
    

# Function to summarize the messages using GPT
async def summarize_messages(messages):
    try:
        summary = await gpt_summary_function(messages)
        return summary
    except Exception as e:
        logging.error(f"Error summarizing messages: {e}")
        return "Could not generate summary."

# Command handler for /analyze
async def analyze_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    n = 500  # Change this to 500 if you want to read 500 lines
    log_file_path = '/var/log/psychochauffeurbot/bot_chat.log'  # Update this path

    try:
        # Read the last n lines specific to the chat ID
        messages = read_last_n_lines(log_file_path, chat_id, n)

        # Debugging output
        print(f"Messages to summarize: {messages}")

        if not messages:
            await context.bot.send_message(chat_id, "Не знайдено повідомлень для аналізу.")
            return
        
        # Extract just the message text from the log lines
        messages_text = [line.split(" - ")[-1].strip() for line in messages]

        # Summarize the messages in Ukrainian
        summary = await gpt_summary_function(messages_text)

        # Send the summary back to the chat
        await context.bot.send_message(chat_id, f"Підсумок останніх {n} повідомлень:\n{summary}")
    except Exception as e:
        logging.error(f"Error in /analyze command: {e}")
        await context.bot.send_message(chat_id, "Виникла помилка при аналізі повідомлень.")

