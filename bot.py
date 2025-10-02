import feedparser
import requests
import json
import os
import re
from bs4 import BeautifulSoup
from datetime import datetime
from telegram import Bot

# ---------------- CONFIG ----------------
BOT_TOKEN = "7839637427:AAE0LL7xeUVJiJusSHaHTOGYAI3kopwxdn4"
CHANNEL_ID = "@football1805"
RSS_URL = "http://feeds.bbci.co.uk/sport/football/rss.xml"
CACHE_FILE = "posted.json"
POSTS_PER_RUN = 5  # 1–5 posts per run
SUMMARY_TRUNCATE = 250  # characters for Telegram read more effect
# ----------------------------------------

def load_posted():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r") as f:
            return set(json.load(f))
    return set()

def save_posted(posted):
    with open(CACHE_FILE, "w") as f:
        json.dump(list(posted), f)

def get_high_quality_image(url):
    """Scrape the main article image for HQ version."""
    try:
        res = requests.get(url, timeout=10)
        soup = BeautifulSoup(res.content, "html.parser")
        # BBC main image usually in figure or div with specific class
        figure = soup.find("figure")
        if figure:
            img = figure.find("img")
            if img and img.get("src"):
                return img["src"]
        # fallback: first large image
        img = soup.find("img")
        if img and img.get("src"):
            return img["src"]
    except:
        return None
    return None

def get_hashtags(title, summary):
    """Generate hashtags from words >2 letters, limit 8."""
    hashtags = set()
    words = re.findall(r'\b\w{3,}\b', title + " " + summary)
    for word in words:
        hashtags.add("#" + word.lower())
    return " ".join(list(hashtags)[:8])

def get_news():
    """Fetch today’s football news from RSS."""
    feed = feedparser.parse(RSS_URL)
    today = datetime.utcnow().date()
    articles = []

    for entry in feed.entries:
        title = entry.title
        summary = BeautifulSoup(entry.summary, "html.parser").get_text()
        link = entry.link
        published_date = datetime(*entry.published_parsed[:6]).date()

        # Only today's posts
        if published_date != today:
            continue

        image_url = get_high_quality_image(link)
        hashtags = get_hashtags(title, summary)

        # Truncate summary for Telegram “read more” drop-down
        if len(summary) > SUMMARY_TRUNCATE:
            summary = summary[:SUMMARY_TRUNCATE] + "..."

        articles.append({
            "title": title,
            "summary": summary,
            "image": image_url,
            "link": link,       # internal tracking only
            "hashtags": hashtags
        })

    return articles

def main():
    bot = Bot(token=BOT_TOKEN)
    posted = load_posted()
    news = get_news()

    count = 0
    for article in news:
        if article["link"] not in posted:
            caption = f'⚽ "{article["title"]}"\n\n{article["summary"]}\n\n{article["hashtags"]}'
            if article["image"]:
                bot.send_photo(chat_id=CHANNEL_ID, photo=article["image"], caption=caption, parse_mode="HTML")
            else:
                bot.send_message(chat_id=CHANNEL_ID, text=caption, parse_mode="HTML")

            posted.add(article["link"])
            count += 1
            if count >= POSTS_PER_RUN:
                break

    # If no new posts, fetch other posts from today not sent
    if count == 0:
        for entry in feedparser.parse(RSS_URL).entries:
            link = entry.link
            if link not in posted:
                title = entry.title
                summary = BeautifulSoup(entry.summary, "html.parser").get_text()
                image_url = get_high_quality_image(link)
                hashtags = get_hashtags(title, summary)
                if len(summary) > SUMMARY_TRUNCATE:
                    summary = summary[:SUMMARY_TRUNCATE] + "..."
                caption = f'⚽ "{title}"\n\n{summary}\n\n{hashtags}'
                if image_url:
                    bot.send_photo(chat_id=CHANNEL_ID, photo=image_url, caption=caption, parse_mode="HTML")
                else:
                    bot.send_message(chat_id=CHANNEL_ID, text=caption, parse_mode="HTML")
                posted.add(link)
                count += 1
                if count >= POSTS_PER_RUN:
                    break

    save_posted(posted)

if __name__ == "__main__":
    main()
