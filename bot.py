import feedparser
import requests
import json
import os
import re
import time
import logging
from bs4 import BeautifulSoup
from datetime import datetime, date
from random import randint
from telegram import Bot, error
from telegram.constants import ParseMode

# --- SETUP: Configure Logging ---
# Configure logging to track activity and errors
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# ---------------- CONFIG ----------------
# NOTE: Read the token from environment variable for secure GitHub Actions use
BOT_TOKEN = os.getenv("BOT_TOKEN", "7839637427:AAE0LL7xeUVJiJusSHaHTOGYAI3kopwxdn4") 
CHANNEL_ID = "@football1805"
RSS_URL = "http://feeds.bbci.co.uk/sport/football/rss.xml"
CACHE_FILE = "posted.json"

# --- EXECUTION CONFIG for a single run (e.g., via GitHub Actions) ---
# The script will randomly choose how many posts to send in this single run.
MIN_POSTS_PER_RUN = 1
MAX_POSTS_PER_RUN = 3

SUMMARY_TRUNCATE = 250  # Max characters for Telegram summary before "..."
API_TIMEOUT = 15        # Timeout for network requests (seconds)
# ----------------------------------------

# --- CACHE FUNCTIONS ---

def load_posted() -> set:
    """Load the set of posted article links from the cache file."""
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r") as f:
                return set(json.load(f))
        except (IOError, json.JSONDecodeError) as e:
            logger.error(f"Error loading cache file {CACHE_FILE}: {e}")
            return set()
    return set()

def save_posted(posted: set):
    """Save the set of posted article links to the cache file."""
    try:
        with open(CACHE_FILE, "w") as f:
            json.dump(list(posted), f, indent=4)
    except IOError as e:
        logger.error(f"Error saving cache file {CACHE_FILE}: {e}")

# --- DATA EXTRACTION & FORMATTING ---

def escape_markdown(text: str) -> str:
    """Escapes special characters for MarkdownV2 formatting."""
    # List of characters to escape: _*[\]()~`>#+-=|{}.!
    return re.sub(r'([_*[\]()~`>#+\-=|{}.!])', r'\\\1', text)

def get_high_quality_image(url: str) -> str | None:
    """Scrape the main article image for a high-quality version."""
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (compatible; RSSBot/1.0;)'}
        res = requests.get(url, timeout=API_TIMEOUT, headers=headers)
        res.raise_for_status()
        soup = BeautifulSoup(res.content, "html.parser")

        # Try to find BBC's main image container
        figure = soup.find("figure")
        if figure:
            img = figure.find("img")
            if img and img.get("src"):
                return img["src"]
        
        # Fallback: first image with an absolute URL
        for img in soup.find_all("img"):
            src = img.get("src")
            if src and src.startswith("http"):
                return src

    except requests.exceptions.RequestException as e:
        logger.warning(f"Failed to fetch or parse article image for {url}: {e}")
    except Exception as e:
        logger.error(f"Unexpected error in image fetching for {url}: {e}")
        
    return None

def get_hashtags(title: str, summary: str) -> str:
    """Generate up to 8 unique hashtags from words >2 letters, excluding stopwords."""
    hashtags = set()
    words = re.findall(r'\b[a-zA-Z]{3,}\b', title + " " + summary)
    
    # Common stopwords
    stopwords = {"and", "the", "for", "with", "from", "that", "this", "it", "not", "but", "who", "was", "will", "has", "can", "out", "new", "all", "get", "got", "say", "bbc", "sport", "one", "two", "what", "how", "why"}
    
    for word in words:
        lower_word = word.lower()
        if lower_word not in stopwords:
            hashtags.add("#" + lower_word)
            
    return " ".join(list(hashtags)[:8])

def format_article(entry) -> dict | None:
    """Extracts and formats article data, handling MarkdownV2 escaping."""
    try:
        title_raw = entry.title
        summary_raw = BeautifulSoup(entry.summary, "html.parser").get_text()
        link = entry.link
        
        # Determine published date (default to min date if not found)
        published_date = datetime(*entry.published_parsed[:6]).date() if entry.get("published_parsed") else date.min
            
        # 1. Scraping and Tagging (using raw strings)
        image_url = get_high_quality_image(link)
        hashtags = get_hashtags(title_raw, summary_raw)

        # 2. Formatting (using escaped strings)
        title_escaped = escape_markdown(title_raw)
        summary_escaped = escape_markdown(summary_raw)

        # Truncate summary
        summary_display = summary_escaped
        if len(summary_raw) > SUMMARY_TRUNCATE:
            summary_display = summary_escaped[:SUMMARY_TRUNCATE].strip() + "..."
            
        # The caption uses MarkdownV2 for the bolded title
        caption = f'⚽ *{title_escaped}*\n\n{summary_display}\n\n{hashtags}'

        return {
            "title": title_raw, 
            "image": image_url,
            "link": link,
            "published_date": published_date,
            "caption": caption
        }
    except Exception as e:
        logger.error(f"Failed to format article from RSS entry: {e}")
        return None

# --- TELEGRAM BOT LOGIC ---

def send_post(bot: Bot, article: dict) -> bool:
    """Sends the formatted article to Telegram."""
    try:
        if article["image"]:
            bot.send_photo(
                chat_id=CHANNEL_ID, 
                photo=article["image"], 
                caption=article["caption"], 
                parse_mode=ParseMode.MARKDOWN_V2
            )
        else:
            bot.send_message(
                chat_id=CHANNEL_ID, 
                text=article["caption"], 
                parse_mode=ParseMode.MARKDOWN_V2
            )
        logger.info(f"SUCCESS: Posted '{article['title']}' to Telegram.")
        return True
    
    except error.TelegramError as e:
        # Log error but don't crash the run
        logger.warning(f"Telegram API Error posting '{article['title']}': {e}")
        return False
    except Exception as e:
        logger.error(f"General error during Telegram send: {e}")
        return False

# --- MAIN EXECUTION FOR SCHEDULED RUN ---

def main():
    """Initializes the bot, checks the feed, posts 1-3 new articles, and exits."""
    logger.info("--- Starting Scheduled Bot Run ---")
    
    # 1. Initialization
    if BOT_TOKEN in ["", "7839637427:AAE0LL7xeUVJiJusSHaHTOGYAI3kopwxdn4"]:
        logger.critical("BOT_TOKEN is missing or using default. Please configure it.")
        return
        
    try:
        bot = Bot(token=BOT_TOKEN)
        bot.get_me() # Quick check to ensure token is valid
    except Exception as e:
        logger.critical(f"Failed to initialize Telegram Bot: {e}")
        return

    posted = load_posted()
    
    posts_to_send = randint(MIN_POSTS_PER_RUN, MAX_POSTS_PER_RUN)
    logger.info(f"Goal for this run: Post {posts_to_send} new article(s).")

    # 2. Fetch RSS Feed
    try:
        feed = feedparser.parse(RSS_URL)
        if feed.status not in [200, 301]:
             logger.error(f"Failed to fetch RSS feed. Status code: {feed.status}")
             return
    except Exception as e:
        logger.critical(f"Error fetching RSS feed: {e}")
        return

    # 3. Filter Articles
    entries_to_post = []
    today = datetime.utcnow().date()
    
    for entry in feed.entries:
        article = format_article(entry)
        if not article:
            continue
            
        # CRITICAL: Always skip already posted links
        if article["link"] in posted:
            continue
            
        # Only consider articles published today
        if article["published_date"] == today:
            entries_to_post.append(article)
            
    # Sort by date/time parsed (newest first)
    entries_to_post.sort(key=lambda x: x["published_date"], reverse=True)
            
    logger.info(f"Found {len(entries_to_post)} new, unposted articles from TODAY.")
    
    # 4. Execution: Post up to the randomized limit
    count = 0
    for article in entries_to_post:
        if count >= posts_to_send:
            break
            
        logger.info(f"Attempting to post: {article['title']}")
        if send_post(bot, article):
            posted.add(article["link"])
            count += 1
            # Small delay to respect API limits, even between the 1-3 posts
            time.sleep(1.5) 
            
    logger.info(f"--- Run Complete: {count} article(s) posted. ---")

    # 5. Final Save and Exit
    save_posted(posted)

if __name__ == "__main__":
    # If run locally, it executes once and exits. 
    # If run via a scheduler, it executes once per trigger and exits.
    main()
