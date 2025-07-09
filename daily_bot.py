import feedparser
import requests
import os
import logging
from datetime import datetime, timedelta

# Configuration
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHANNEL_ID = os.getenv('TELEGRAM_CHANNEL_ID')
RSS_URL = 'https://news.smol.ai/rss.xml'

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def send_telegram_message(message: str) -> bool:
    """Send message to Telegram channel"""
    url = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage'
    
    # Split long messages if needed
    if len(message) > 4000:
        message = message[:4000] + "... (truncated)"
    
    data = {
        'chat_id': TELEGRAM_CHANNEL_ID,
        'text': message,
        'parse_mode': 'Markdown',
        'disable_web_page_preview': False
    }
    
    try:
        response = requests.post(url, data=data, timeout=30)
        response.raise_for_status()
        return True
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to send message: {e}")
        return False

def is_recent_post(entry, hours=25):
    """Check if post is from the last 25 hours (buffer for daily runs)"""
    try:
        import email.utils
        # Try parsing the published date
        published_str = entry.get('published', '')
        if published_str:
            # Parse RFC 2822 format (common in RSS)
            time_tuple = email.utils.parsedate_tz(published_str)
            if time_tuple:
                import calendar
                published_timestamp = calendar.timegm(time_tuple[:9])
                if time_tuple[9]:
                    published_timestamp -= time_tuple[9]  # Adjust for timezone
                
                cutoff_timestamp = datetime.now().timestamp() - (hours * 3600)
                return published_timestamp > cutoff_timestamp
    except Exception as e:
        logger.debug(f"Date parsing error: {e}")
    
    # If we can't parse date, assume it's recent (better to send than miss)
    return True

def format_post(entry) -> str:
    """Format RSS entry for Telegram"""
    title = entry.get('title', 'No title')
    link = entry.get('link', '')
    summary = entry.get('summary', entry.get('description', ''))
    
    # Clean up summary
    if summary:
        import re
        summary = re.sub(r'<[^>]+>', '', summary)
        if len(summary) > 300:
            summary = summary[:300] + "..."
    
    message = f"🤖 **{title}**\n\n"
    
    if summary:
        message += f"{summary}\n\n"
    
    if link:
        message += f"🔗 [Read full article]({link})"
    
    return message

def main():
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHANNEL_ID:
        logger.error("Missing required environment variables")
        return
    
    try:
        logger.info(f"Fetching RSS feed from {RSS_URL}")
        feed = feedparser.parse(RSS_URL)
        
        if not feed.entries:
            logger.warning("No entries found in RSS feed")
            return
        
        # Get recent posts (last 24 hours)
        recent_posts = [entry for entry in feed.entries if is_recent_post(entry)]
        
        if not recent_posts:
            # If no recent posts, send the latest post anyway
            recent_posts = [feed.entries[0]] if feed.entries else []
            logger.info("No posts from last 24h, sending latest post")
        
        logger.info(f"Found {len(recent_posts)} recent posts")
        
        # Send summary message
        if len(recent_posts) == 1:
            summary = "📰 **Daily AI News Update**\n\nHere's today's highlight:\n\n"
        else:
            summary = f"📰 **Daily AI News Update**\n\n{len(recent_posts)} new posts from the last 24 hours:\n\n"
        
        # Combine all posts into one message (or send separately if too long)
        all_content = summary
        
        for i, post in enumerate(recent_posts[:5]):  # Limit to 5 posts max
            post_content = format_post(post)
            
            # Check if adding this post would exceed Telegram limit
            if len(all_content + post_content) > 3500:
                # Send current message and start a new one
                send_telegram_message(all_content)
                all_content = f"📰 **Continued...**\n\n{post_content}\n\n"
            else:
                all_content += post_content + "\n\n---\n\n"
        
        # Send final message
        if all_content.strip():
            send_telegram_message(all_content)
            logger.info("Daily update sent successfully!")
        
        # Add footer with source
        footer = "🔔 Daily updates from [news.smol.ai](https://news.smol.ai)"
        send_telegram_message(footer)
        
    except Exception as e:
        logger.error(f"Error: {e}")
        # Send error notification to channel
        error_msg = f"⚠️ Daily AI news bot encountered an error: {str(e)}"
        send_telegram_message(error_msg)

if __name__ == "__main__":
    main()
