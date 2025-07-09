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

def extract_top_news_items(content: str, max_items: int = 5) -> list:
    """Extract top news items from the post content"""
    import re
    
    # Remove HTML tags
    content = re.sub(r'<[^>]+>', '', content)
    
    # Look for news patterns - items that start with company names or key terms
    news_patterns = [
        r'(?:^|\n)([A-Z][A-Za-z0-9&\s]{2,30}(?:\s(?:announced|released|launched|introduced|updated|acquired|secured|published|reached|achieved|expanded|partnered|developed|created|unveiled|debuted|hired|filed|raised|reported|shared|posted|confirmed|revealed|showed|demonstrated|teased|previewed|broke|disclosed|leaked|sparked|gained|surpassed|topped|dominated|won|beat|outperformed|defeated|overtook|passed|exceeded|hit|crossed|reached|climbed|soared|jumped|skyrocketed|plummeted|dropped|fell|declined|crashed|tumbled|slumped|dipped|slid)).*?)(?=\n[A-Z]|\n-|\n\*|\n\d+\.|\n$|$)',
        r'(?:^|\n)(.*?(?:AI|ML|LLM|GPU|API|model|dataset|algorithm|neural|transformer|chatgpt|claude|gemini|grok|llama|mistral|anthropic|openai|google|microsoft|meta|tesla|nvidia|amd|intel).*?)(?=\n[A-Z]|\n-|\n\*|\n\d+\.|\n$|$)',
        r'(?:^|\n)- (.*?)(?=\n-|\n\*|\n\d+\.|\n[A-Z][a-z]|\n$|$)',
        r'(?:^|\n)\* (.*?)(?=\n-|\n\*|\n\d+\.|\n[A-Z][a-z]|\n$|$)',
        r'(?:^|\n)\d+\.\s*(.*?)(?=\n\d+\.|\n-|\n\*|\n[A-Z][a-z]|\n$|$)'
    ]
    
    news_items = []
    content_lines = content.split('\n')
    
    # Look for bullet points and numbered lists
    for line in content_lines:
        line = line.strip()
        if not line:
            continue
            
        # Skip very short lines
        if len(line) < 20:
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

def extract_links_from_text(text: str) -> list:
    """Extract URLs from text"""
    import re
    # Pattern to match URLs
    url_pattern = r'https?://[^\s\)]+(?=\s|\)|$|,|\.)'
    links = re.findall(url_pattern, text)
    return links

def format_news_items(news_items: list, post_title: str, post_link: str) -> str:
    """Format extracted news items for Telegram"""
    if not news_items:
        return f"🤖 **{post_title}**\n\n📰 Check out today's AI news roundup!\n\n🔗 [Read full post]({post_link})"
    
    message = f"🤖 **{post_title}**\n\n📰 **Top {len(news_items)} AI News Items:**\n\n"
    
    for i, item in enumerate(news_items, 1):
        # Truncate very long items
        text = item['text']
        if len(text) > 200:
            text = text[:200] + "..."
        
        message += f"**{i}.** {text}\n"
        
        # Add links if found
        if item['links']:
            for link in item['links'][:2]:  # Limit to 2 links per item
                message += f"   🔗 [Source]({link})\n"
        
        message += "\n"
    
    message += f"📄 [Read full post with all details]({post_link})"
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
