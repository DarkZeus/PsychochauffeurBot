import os
import sys
import logging
import asyncio
import html
from logging.handlers import RotatingFileHandler
from modules.file_manager import ensure_directories
import threading
from typing import Set, Optional, Tuple
from datetime import datetime
import pytz
import time
from modules.const import Config

# Timezone constants
KYIV_TZ = pytz.timezone('Europe/Kyiv')

# Path constants
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(PROJECT_ROOT, 'data')
LOG_DIR = os.path.join(PROJECT_ROOT, 'logs')
USED_WORDS_FILE = os.path.join(DATA_DIR, "used_words.csv")


# Custom formatter for Kyiv timezone
class KyivTimezoneFormatter(logging.Formatter):
    """Custom formatter that uses Kyiv timezone"""
    def formatTime(self, record, datefmt=None):
        dt = datetime.fromtimestamp(record.created).astimezone(KYIV_TZ)
        return dt.strftime(datefmt) if datefmt else dt.strftime("%Y-%m-%d %H:%M:%S %z")

# Chat-specific daily log handler
class DailyLogHandler(logging.Handler):
    def emit(self, record):
        # Ensure chat_id is included in the record if available
        if hasattr(record, 'chat_id'):
            record.chattitle = getattr(record, 'chattitle', 'Unknown')
            record.username = getattr(record, 'username', 'Unknown')
        else:
            record.chat_id = 'N/A'  # Default value if chat_id is not present
            record.chattitle = 'Unknown'  # Default value for chattitle
            record.username = 'Unknown'  # Default value for username
        try:
            # Format date in Kyiv timezone
            date = datetime.now(KYIV_TZ)
            
            # Create path
            if record.chat_id is not None:
                chat_log_dir = os.path.join(LOG_DIR, f"chat_{record.chat_id}")
                os.makedirs(chat_log_dir, exist_ok=True)
                daily_log_path = os.path.join(chat_log_dir, f"chat_{date.strftime('%Y-%m-%d')}.log")
            else:
                daily_log_path = os.path.join(LOG_DIR, f"chat_{date.strftime('%Y-%m-%d')}.log")
            
            msg = self.format(record)
            with open(daily_log_path, 'a', encoding='utf-8') as f:
                f.write(msg + '\n')
        except Exception:
            self.handleError(record)

# Telegram error reporting handler
class TelegramErrorHandler(logging.Handler):
    """Custom handler for sending error logs to Telegram channel"""
    def __init__(self, bot, channel_id, rate_limit=1):
        super().__init__()
        self.bot = bot
        self.channel_id = channel_id
        self.buffer = []
        self.last_sent = 0
        self.rate_limit = rate_limit  # Minimum seconds between messages
        
        try:
            self.loop = asyncio.get_event_loop()
        except RuntimeError:
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)

    async def send_message(self, error_msg: str) -> None:
        """
        Send message to Telegram with retry logic.
        
        Args:
            error_msg: Error message to send
        """
        max_retries = 3
        retry_delay = 1
        
        for attempt in range(max_retries):
            try:
                escaped_msg = error_msg.replace('_', '\\_').replace('*', '\\*').replace('`', '\\`')
                await self.bot.bot.send_message(
                    chat_id=self.channel_id,
                    text=escaped_msg,
                    parse_mode='MarkdownV2'
                )
                return
            except Exception as e:
                if attempt == max_retries - 1:
                    general_logger.error(f"Failed to send error message to Telegram after {max_retries} attempts: {e}")
                    try:
                        await self.bot.bot.send_message(
                            chat_id=self.channel_id,
                            text=html.escape(error_msg),
                            parse_mode=None
                        )
                    except Exception as final_e:
                        general_logger.error(f"Final attempt to send message failed: {final_e}")
                await asyncio.sleep(retry_delay * (attempt + 1))

    def format_error_message(self, record: logging.LogRecord) -> str:
        """
        Format the error message with all relevant information.
        """
        current_time = datetime.now(KYIV_TZ).strftime('%Y-%m-%d %H:%M:%S %Z')
        
        chat_id = getattr(record, 'chat_id', 'N/A')
        username = getattr(record, 'username', 'N/A')
        chat_title = getattr(record, 'chattitle', 'N/A')
        
        error_msg = (
            f"🚨 *Error Report*\n"
            f"*Time:* {current_time}\n"
            f"*Level:* {record.levelname}\n"
            f"*Location:* {record.pathname}:{record.lineno}\n"
            f"*Function:* {record.funcName}\n"
            f"*Chat ID:* {chat_id}\n"
            f"*Username:* {username}\n"
            f"*Chat Title:* {chat_title}\n"
            f"*Message:*\n"
            f"```\n{self.format(record)}\n```"
        )
        return error_msg

    async def emit_async(self, record):
        try:
            error_msg = self.format_error_message(record)
            now = time.time()
            
            if now - self.last_sent >= self.rate_limit:
                await self.send_message(error_msg)
                self.last_sent = now
            else:
                self.buffer.append(error_msg)
        except Exception as e:
            print(f"Error in TelegramErrorHandler: {e}")
            self.handleError(record)

    def emit(self, record):
        try:
            coroutine = self.emit_async(record)
            try:
                asyncio.create_task(coroutine)
            except RuntimeError:
                self.loop.run_until_complete(coroutine)
        except Exception as e:
            print(f"Error in TelegramErrorHandler.emit: {e}")
            self.handleError(record)

# Initialize logging system
def initialize_logging() -> Tuple[logging.Logger, logging.Logger, logging.Logger]:
    """Set up all loggers and handlers"""
    if not ensure_directories():
        sys.exit(1)
    
    class CustomFormatter(logging.Formatter):
        def format(self, record):
            record.chat_id = getattr(record, 'chat_id', 'N/A')
            record.chattitle = getattr(record, 'chattitle', 'Unknown')
            record.username = getattr(record, 'username', 'Unknown')
            return super().format(record)

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(KyivTimezoneFormatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    
    # --- General Logger ---
    general_logger = logging.getLogger('general_logger')
    general_logger.setLevel(logging.INFO)
    
    general_file_handler = RotatingFileHandler(
        os.path.join(LOG_DIR, 'general.log'),
        maxBytes=5*1024*1024,
        backupCount=3,
        encoding='utf-8'
    )
    general_file_handler.setFormatter(CustomFormatter('%(asctime)s - %(name)s - %(levelname)s - %(chat_id)s - %(chattitle)s - %(username)s - %(message)s'))
    general_file_handler.setLevel(logging.INFO)
    
    general_logger.addHandler(console_handler)
    general_logger.addHandler(general_file_handler)
    general_logger.propagate = False
    
    # --- Chat Logger ---
    chat_logger = logging.getLogger('chat_logger')
    chat_logger.setLevel(logging.INFO)
    
    chat_file_handler = RotatingFileHandler(
        os.path.join(LOG_DIR, 'chat.log'),
        maxBytes=5*1024*1024,
        backupCount=3,
        encoding='utf-8'
    )
    chat_file_handler.setFormatter(CustomFormatter('%(asctime)s - %(name)s - %(levelname)s - %(chat_id)s - %(chattitle)s - %(username)s - %(message)s'))
    
    daily_handler = DailyLogHandler()
    daily_handler.setLevel(logging.INFO)
    daily_handler.setFormatter(CustomFormatter('%(asctime)s - %(name)s - %(levelname)s - %(chat_id)s - %(chattitle)s - %(username)s - %(message)s'))
    
    chat_logger.addHandler(console_handler)
    chat_logger.addHandler(chat_file_handler)
    chat_logger.addHandler(daily_handler)
    chat_logger.propagate = False
    
    # --- Error Logger ---
    error_logger = logging.getLogger('error_logger')
    error_logger.setLevel(logging.ERROR)
    
    error_file_handler = RotatingFileHandler(
        os.path.join(LOG_DIR, 'error.log'),
        maxBytes=5*1024*1024,
        backupCount=3,
        encoding='utf-8'
    )
    error_file_handler.setFormatter(KyivTimezoneFormatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    
    error_logger.addHandler(console_handler)
    error_logger.addHandler(error_file_handler)
    error_logger.propagate = False
    
    # Suppress other library logs
    logging.getLogger("httpx").setLevel(logging.WARNING)
    
    # Log initialization success
    general_logger.info("Logging system initialized successfully")
    chat_logger.info("Chat logging system initialized successfully")
    error_logger.info("Error logging system initialized successfully")
    
    print(f"Log files are being written to: {LOG_DIR}")
    
    return general_logger, chat_logger, error_logger

# Initialize telegram error handler
def init_error_handler(bot, ERROR_CHANNEL_ID):
    """Initialize error handler with bot instance"""
    if not bot or not bot.is_connected():
        logging.getLogger('general_logger').warning("Telegram bot is not connected")
        return
        
    error_logger = logging.getLogger('error_logger')
    handler = TelegramErrorHandler(bot, ERROR_CHANNEL_ID)
    handler.setFormatter(KyivTimezoneFormatter(
        '%(asctime)s - %(name)s - %(levelname)s\nFile: %(pathname)s:%(lineno)d\nFunction: %(funcName)s\nMessage: %(message)s'
    ))
    error_logger.addHandler(handler)

def get_daily_log_path(chat_id: str, date: Optional[datetime] = None, chat_title: Optional[str] = None) -> str:
    """
    Generate the path for a daily log file.
    
    Args:
        chat_id: Chat ID
        date: Date for the log file, defaults to current date
        chat_title: Optional chat title to save
        
    Returns:
        str: Path to the log file
    """
    if date is None:
        date = datetime.now(KYIV_TZ)
    log_dir = os.path.join(LOG_DIR, f"chat_{chat_id}")
    os.makedirs(log_dir, exist_ok=True)  # Ensure directory exists
    
    if chat_title:
        chat_name_file = os.path.join(log_dir, "chat_name.txt")
        with open(chat_name_file, 'w', encoding='utf-8') as f:
            f.write(chat_title)
    
    return os.path.join(log_dir, f"chat_{date.strftime('%Y-%m-%d')}.log")

def read_last_n_lines(file_path: str, n: int) -> list:
    """
    Read the last n lines of a file.
    
    Args:
        file_path: Path to the file
        n: Number of lines to read
        
    Returns:
        list: List of lines
    """
    with open(file_path, 'r', encoding='utf-8') as file:
        lines = file.readlines()
        return lines[-n:]  # Return the last n lines

# Initialize logging when this module is imported
general_logger, chat_logger, error_logger = initialize_logging()