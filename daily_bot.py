import feedparser
import requests
import os
import logging
import time
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
        logger.info(f"Response status: {response.status_code}")
        response.raise_for_status()
        return True
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to send message: {e}")
        logger.error(f"Response content: {response.text if 'response' in locals() else 'No response'}")
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

def extract_links_from_text(text: str) -> list:
    """Extract URLs from text"""
    import re
    # Pattern to match URLs
    url_pattern = r'https?://[^\s\)]+(?=\s|\)|$|,|\.)'
    links = re.findall(url_pattern, text)
    return links

def extract_top_news_items(content: str, max_items: int = 5) -> list:
    """Extract top news items from the post content"""
    import re
    
    # Remove HTML tags
    content = re.sub(r'<[^>]+>', '', content)
    
    news_items = []
    content_lines = content.split('\n')
    
    # Look for bullet points and numbered lists
    for line in content_lines:
        line = line.strip()
        if not line:
            continue
            
        # Skip very short lines
        if len(line) < 30:
            continue
            
        # Look for lines that start with bullets, numbers, or company names
        if (re.match(r'^[-*•]\s*', line) or 
            re.match(r'^\d+\.\s*', line) or
            re.match(r'^[A-Z][a-zA-Z0-9&\s]{2,20}(?:\s(?:announced|released|launched|introduced|updated))', line) or
            any(keyword in line.lower() for keyword in ['announced', 'released', 'launched', 'introduced', 'updated', 'acquired', 'secured', 'published', 'reached', 'achieved'])):
            
            # Clean up the line
            clean_line = re.sub(r'^[-*•]\s*', '', line)
            clean_line = re.sub(r'^\d+\.\s*', '', clean_line)
            clean_line = clean_line.strip()
            
            if len(clean_line) > 30 and clean_line not in [item['text'] for item in news_items]:
                news_items.append({
                    'text': clean_line,
                    'links': extract_links_from_text(clean_line)
                })
                
        # Also look for lines that mention key AI companies/models
        elif any(keyword in line.lower() for keyword in ['openai', 'anthropic', 'google', 'microsoft', 'meta', 'tesla', 'nvidia', 'chatgpt', 'claude', 'gemini', 'grok', 'llama']):
            if len(line) > 30 and line not in [item['text'] for item in news_items]:
                news_items.append({
                    'text': line,
                    'links': extract_links_from_text(line)
                })
    
    # Sort by length (longer items are usually more informative) and return top items
    news_items.sort(key=lambda x: len(x['text']), reverse=True)
    return news_items[:max_items]

def format_news_items(news_items: list, post_title: str, post_link: str) -> str:
    """Format extracted news items for Telegram"""
    if not news_items:
        return f"🤖 *{post_title}*\n\n📰 Check out today's AI news roundup!\n\n🔗 [Read full post]({post_link})"
    
    message = f"🤖 *{post_title}*\n\n📰 *Top {len(news_items)} AI News Items:*\n\n"
    
    for i, item in enumerate(news_items, 1):
        # Truncate very long items
        text = item['text']
        if len(text) > 150:
            text = text[:150] + "..."
        
        # Escape markdown characters in text
        text = text.replace('*', '\\*').replace('_', '\\_').replace('[', '\\[').replace('`', '\\`')
        
        message += f"*{i}.* {text}\n"
        
        # Add links if found
        if item['links']:
            for link in item['links'][:1]:  # Limit to 1 link per item
                message += f"   🔗 [Source]({link})\n"
        
        message += "\n"
    
    message += f"📄 [Read full post with all details]({post_link})"
    return message

def format_simple_post(entry) -> str:
    """Simple fallback format for posts"""
    title = entry.get('title', 'AI News Update')
    link = entry.get('link', '')
    summary = entry.get('summary', entry.get('description', ''))
    
    # Clean up summary
    if summary:
        import re
        summary = re.sub(r'<[^>]+>', '', summary)
        if len(summary) > 200:
            summary = summary[:200] + "..."
        # Escape markdown
        summary = summary.replace('*', '\\*').replace('_', '\\_').replace('[', '\\[').replace('`', '\\`')
    
    # Escape title
    title = title.replace('*', '\\*').replace('_', '\\_').replace('[', '\\[').replace('`', '\\`')
    
    message = f"🤖 *{title}*\n\n"
    
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
        
        # Get recent posts (last 25 hours)
        recent_posts = [entry for entry in feed.entries if is_recent_post(entry)]
        
        if not recent_posts:
            # If no recent posts, send the latest post anyway
            recent_posts = [feed.entries[0]] if feed.entries else []
            logger.info("No posts from last 25h, sending latest post")
        
        logger.info(f"Found {len(recent_posts)} recent posts")
        
        # Send a simple summary first
        summary = f"📰 *Daily AI News Summary*\n\nProcessing {len(recent_posts)} recent posts..."
        send_telegram_message(summary)
        
        # Process each post
        for i, post in enumerate(recent_posts[:2]):  # Limit to 2 most recent posts
            try:
                title = post.get('title', 'AI News Update')
                link = post.get('link', '')
                content = post.get('summary', post.get('description', ''))
                
                logger.info(f"Processing post: {title}")
                
                # Try to extract news items
                news_items = extract_top_news_items(content, max_items=3)
                
                if news_items:
                    message = format_news_items(news_items, title, link)
                    logger.info(f"Extracted {len(news_items)} news items")
                else:
                    # Fallback to simple format
                    message = format_simple_post(post)
                    logger.info("Using simple format (no items extracted)")
                
                # Send the message
                if send_telegram_message(message):
                    logger.info(f"Successfully sent post {i+1}")
                    time.sleep(2)  # Rate limiting
                else:
                    logger.error(f"Failed to send post {i+1}")
                    
            except Exception as e:
                logger.error(f"Error processing post {i+1}: {e}")
                # Try to send a simple error message
                error_message = f"⚠️ Error processing post: {post.get('title', 'Unknown')}"
                send_telegram_message(error_message)
        
        # Send footer
        footer = "🔔 Daily AI news from [news.smol.ai](https://news.smol.ai)"
        send_telegram_message(footer)
        
        logger.info("Daily update completed!")
        
    except Exception as e:
        logger.error(f"Error: {e}")
        # Send error notification to channel
        error_msg = f"⚠️ Daily AI news bot encountered an error: {str(e)}"
        send_telegram_message(error_msg)

if __name__ == "__main__":
    main()
