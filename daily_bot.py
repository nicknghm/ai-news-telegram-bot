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
    """Format extracted news items for Telegram with smart truncation"""
    
    # Escape title
    title = post_title.replace('*', '\\*').replace('_', '\\_').replace('[', '\\[').replace('`', '\\`')
    
    # Start building the message
    header = f"🤖 *{title}*\n\n"
    footer = f"\n📄 [Read full post]({post_link})"
    
    # Calculate available space for content
    available_space = 3800 - len(header) - len(footer)  # Buffer for safety
    
    if not news_items:
        content = "📰 Check out today's AI news roundup!"
        return header + content + footer
    
    # Build news items section
    news_header = f"📰 *Top AI News:*\n\n"
    content = news_header
    
    # Calculate space per item (rough estimate)
    space_per_item = (available_space - len(news_header)) // min(len(news_items), 3)
    
    items_added = 0
    for i, item in enumerate(news_items[:3]):  # Max 3 items
        # Escape and clean text
        text = item['text']
        text = text.replace('*', '\\*').replace('_', '\\_').replace('[', '\\[').replace('`', '\\`')
        
        # Smart truncation: find good breaking point
        max_text_length = min(space_per_item - 100, 120)  # Reserve space for formatting and links
        
        if len(text) > max_text_length:
            # Try to break at sentence boundary
            truncated = text[:max_text_length]
            last_period = truncated.rfind('.')
            last_comma = truncated.rfind(',')
            last_space = truncated.rfind(' ')
            
            # Choose best break point
            if last_period > max_text_length - 50:
                text = text[:last_period + 1]
            elif last_comma > max_text_length - 30:
                text = text[:last_comma] + "..."
            elif last_space > max_text_length - 20:
                text = text[:last_space] + "..."
            else:
                text = text[:max_text_length - 3] + "..."
        
        # Format item
        item_text = f"*{i+1}.* {text}\n"
        
        # Add link if available
        if item['links']:
            item_text += f"   🔗 [Source]({item['links'][0]})\n"
        
        item_text += "\n"
        
        # Check if adding this item would exceed our space
        if len(content + item_text) > available_space:
            if items_added == 0:  # Must include at least one item
                # Truncate this item more aggressively
                max_emergency_length = available_space - len(content) - 100
                if max_emergency_length > 50:
                    emergency_text = item['text'][:max_emergency_length] + "..."
                    emergency_text = emergency_text.replace('*', '\\*').replace('_', '\\_').replace('[', '\\[').replace('`', '\\`')
                    content += f"*1.* {emergency_text}\n\n"
                    items_added = 1
            break
        
        content += item_text
        items_added += 1
    
    # Final message assembly
    final_message = header + content + footer
    
    # Final safety check - if still too long, do emergency truncation
    if len(final_message) > 3900:
        # Calculate how much to cut
        excess = len(final_message) - 3900
        # Cut from the content, not the header or footer
        content_end = len(header + content)
        footer_start = content_end
        
        # Truncate content before footer
        safe_content = content[:-excess-20] + "...\n\n"
        final_message = header + safe_content + footer
    
    return final_message

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
        
        # Send all content in ONE message per post
        for i, post in enumerate(recent_posts[:1]):  # Limit to 1 most recent post to avoid spam
            try:
                title = post.get('title', 'AI News Update')
                link = post.get('link', '')
                content = post.get('summary', post.get('description', ''))
                
                logger.info(f"Processing post: {title}")
                
                # Try to extract news items
                news_items = extract_top_news_items(content, max_items=4)
                
                if news_items:
                    message = format_news_items(news_items, title, link)
                    logger.info(f"Extracted {len(news_items)} news items")
                else:
                    # Fallback to simple format
                    message = format_simple_post(post)
                    logger.info("Using simple format (no items extracted)")
                
                # Log message length for debugging
                logger.info(f"Message length: {len(message)} characters")
                
                # Send the single comprehensive message
                if send_telegram_message(message):
                    logger.info(f"Successfully sent comprehensive update")
                else:
                    logger.error(f"Failed to send update")
                    
            except Exception as e:
                logger.error(f"Error processing post: {e}")
                # Send a simple error message
                error_message = f"⚠️ Error processing today's AI news. Please check [news.smol.ai](https://news.smol.ai) directly."
                send_telegram_message(error_message)
        
        logger.info("Daily update completed!")
        
    except Exception as e:
        logger.error(f"Error: {e}")
        # Send error notification to channel
        error_msg = f"⚠️ Daily AI news bot encountered an error: {str(e)}"
        send_telegram_message(error_msg)

if __name__ == "__main__":
    main()
