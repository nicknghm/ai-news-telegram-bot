import feedparser
import requests
import os
import logging
import time
import re
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple

# Configuration
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHANNEL_ID = os.getenv('TELEGRAM_CHANNEL_ID')
RSS_URL = 'https://news.smol.ai/rss.xml'

# Telegram limits
TELEGRAM_MAX_LENGTH = 4096
TELEGRAM_MAX_CAPTION_LENGTH = 1024

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def escape_markdown_v2(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2"""
    # List of characters that need escaping in MarkdownV2
    escape_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    
    for char in escape_chars:
        text = text.replace(char, f'\\{char}')
    
    return text


def send_telegram_message(message: str, parse_mode: str = 'MarkdownV2') -> bool:
    """Send message to Telegram channel with retry logic"""
    url = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage'
    
    # Ensure message doesn't exceed Telegram's limit
    if len(message) > TELEGRAM_MAX_LENGTH:
        message = message[:TELEGRAM_MAX_LENGTH - 20] + '\n\n\\.\\.\\.truncated'
    
    data = {
        'chat_id': TELEGRAM_CHANNEL_ID,
        'text': message,
        'parse_mode': parse_mode,
        'disable_web_page_preview': False
    }
    
    # Retry logic
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = requests.post(url, data=data, timeout=30)
            
            if response.status_code == 200:
                logger.info("Message sent successfully")
                return True
            else:
                logger.error(f"API error: {response.status_code} - {response.text}")
                
                # If it's a parse error, try with plain text
                if "can't parse" in response.text.lower() and parse_mode != 'HTML':
                    logger.info("Retrying with plain text due to parse error")
                    data['parse_mode'] = None
                    continue
                    
        except requests.exceptions.RequestException as e:
            logger.error(f"Request failed (attempt {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)  # Exponential backoff
                
    return False


def parse_rss_date(date_str: str) -> Optional[datetime]:
    """Parse various RSS date formats"""
    import email.utils
    
    try:
        # Try RFC 2822 format first (common in RSS)
        time_tuple = email.utils.parsedate_tz(date_str)
        if time_tuple:
            import calendar
            timestamp = calendar.timegm(time_tuple[:9])
            if time_tuple[9]:
                timestamp -= time_tuple[9]  # Adjust for timezone
            return datetime.fromtimestamp(timestamp)
    except Exception:
        pass
    
    # Try common date formats manually
    date_formats = [
        '%a, %d %b %Y %H:%M:%S %z',  # RFC 2822
        '%a, %d %b %Y %H:%M:%S %Z',  # RFC 2822 with timezone name
        '%Y-%m-%dT%H:%M:%S%z',       # ISO 8601 with timezone
        '%Y-%m-%dT%H:%M:%SZ',        # ISO 8601 UTC
        '%Y-%m-%d %H:%M:%S',         # Common format
        '%Y-%m-%d',                  # Date only
    ]
    
    for fmt in date_formats:
        try:
            return datetime.strptime(date_str.strip(), fmt)
        except ValueError:
            continue
    
    # Try without timezone info
    date_str_no_tz = re.sub(r'\s*\+\d{4}


def is_recent_post(entry: dict, hours: int = 25) -> bool:
    """Check if post is from the last N hours"""
    published_str = entry.get('published', entry.get('updated', ''))
    
    if not published_str:
        # If no date, assume it's recent
        return True
    
    published_date = parse_rss_date(published_str)
    if published_date:
        cutoff_date = datetime.now() - timedelta(hours=hours)
        return published_date > cutoff_date
    
    # If we can't parse date, assume it's recent
    return True


def clean_html(text: str) -> str:
    """Remove HTML tags and decode entities"""
    import html
    
    # Remove HTML tags
    text = re.sub(r'<[^>]+>', '', text)
    
    # Decode HTML entities
    text = html.unescape(text)
    
    # Clean up extra whitespace
    text = re.sub(r'\s+', ' ', text)
    
    return text.strip()


def extract_url_from_text(text: str) -> Optional[str]:
    """Extract the first URL from text"""
    url_pattern = r'https?://[^\s\)<>\[\]]+(?:[^\s\)<>\[\]]*[^\s\)<>\[\].,;:!?\'"»])?'
    match = re.search(url_pattern, text)
    return match.group(0) if match else None


def extract_news_items(content: str, max_items: int = 5) -> List[Dict[str, str]]:
    """Extract news items with improved pattern matching"""
    content = clean_html(content)
    news_items = []
    
    # Split by common delimiters
    lines = re.split(r'\n|(?<=[.!?])\s+(?=[A-Z])', content)
    
    # Keywords that indicate news
    action_keywords = [
        'announced', 'released', 'launched', 'introduced', 'unveiled',
        'debuted', 'published', 'acquired', 'raised', 'secured',
        'partnered', 'collaborated', 'achieved', 'reached', 'surpassed',
        'developed', 'created', 'built', 'deployed', 'updated'
    ]
    
    # Company/product patterns
    company_pattern = r'\b(?:' + '|'.join([
        'OpenAI', 'Anthropic', 'Google', 'Microsoft', 'Meta', 'Apple',
        'Amazon', 'NVIDIA', 'Tesla', 'DeepMind', 'Stability AI',
        'Hugging Face', 'Mistral', 'Cohere', 'Inflection', 'Character\.AI',
        'Midjourney', 'RunwayML', 'Perplexity', 'Claude', 'ChatGPT',
        'GPT-\d+', 'Gemini', 'LLaMA', 'DALL-E', 'Copilot', 'Bard'
    ]) + r')\b'
    
    seen_items = set()
    
    for line in lines:
        line = line.strip()
        
        # Skip short lines or duplicates
        if len(line) < 30 or line in seen_items:
            continue
        
        # Check if line contains relevant keywords
        line_lower = line.lower()
        has_action = any(keyword in line_lower for keyword in action_keywords)
        has_company = re.search(company_pattern, line, re.IGNORECASE)
        
        # Score the line
        score = 0
        if has_action:
            score += 2
        if has_company:
            score += 2
        if re.match(r'^[-•*]\s*', line):  # Bullet point
            score += 1
        if re.match(r'^\d+\.\s*', line):  # Numbered list
            score += 1
        
        if score >= 2:  # Threshold for inclusion
            # Clean the line
            clean_line = re.sub(r'^[-•*]\s*', '', line)
            clean_line = re.sub(r'^\d+\.\s*', '', clean_line)
            
            # Extract URL if present
            url = extract_url_from_text(clean_line)
            
            news_items.append({
                'text': clean_line,
                'url': url,
                'score': score
            })
            seen_items.add(line)
    
    # Sort by score and return top items
    news_items.sort(key=lambda x: x['score'], reverse=True)
    return news_items[:max_items]


def create_punchy_summary(text: str, max_length: int = 80) -> str:
    """Create a concise summary of news item"""
    # Try to extract key components
    patterns = [
        # Company + action + product/detail
        r'([A-Z][a-zA-Z\s&]+?)\s+(announced|released|launched|introduced|unveiled|acquired|raised|secured)\s+(.{10,50})',
        # Model/Product name pattern
        r'([A-Z][a-zA-Z0-9\s-]+?)\s+(is|are|was|were|has|have)\s+(.{10,50})',
        # Achievement pattern
        r'(.{10,30})\s+(reached|achieved|surpassed|hit)\s+(.{10,30})',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            summary = ' '.join(match.groups())
            if len(summary) <= max_length:
                return summary
    
    # Fallback: smart truncation
    if len(text) <= max_length:
        return text
    
    # Try to break at sentence boundary
    sentences = re.split(r'[.!?]', text)
    if sentences and len(sentences[0]) <= max_length:
        return sentences[0].strip()
    
    # Last resort: truncate at word boundary
    words = text.split()
    summary = ""
    for word in words:
        if len(summary) + len(word) + 1 <= max_length - 3:
            summary += word + " "
        else:
            break
    
    return summary.strip() + "..."


def format_telegram_message(entry: dict, news_items: List[Dict[str, str]]) -> str:
    """Format message for Telegram with MarkdownV2"""
    title = entry.get('title', 'AI News Update')
    link = entry.get('link', '')
    
    # Build message parts
    parts = []
    
    # Header with emoji and title
    escaped_title = escape_markdown_v2(title)
    parts.append(f"🤖 *{escaped_title}*")
    parts.append("")  # Empty line
    
    if news_items:
        parts.append("📰 *Top AI News:*")
        parts.append("")
        
        for i, item in enumerate(news_items[:5], 1):
            summary = create_punchy_summary(item['text'])
            escaped_summary = escape_markdown_v2(summary)
            
            # Add numbered item
            parts.append(f"{i}\\. {escaped_summary}")
            
            # Add link if available
            if item.get('url'):
                escaped_url = escape_markdown_v2(item['url'])
                parts.append(f"   🔗 [Link]({escaped_url})")
            
            parts.append("")  # Empty line between items
    else:
        # Fallback content
        summary = entry.get('summary', entry.get('description', ''))
        if summary:
            summary = clean_html(summary)
            if len(summary) > 200:
                summary = summary[:197] + "..."
            escaped_summary = escape_markdown_v2(summary)
            parts.append(escaped_summary)
            parts.append("")
    
    # Footer with read more link
    if link:
        escaped_link = escape_markdown_v2(link)
        parts.append(f"📄 [Read full post]({escaped_link})")
    
    # Join all parts
    message = '\n'.join(parts)
    
    # Final length check
    if len(message) > TELEGRAM_MAX_LENGTH - 100:
        # If still too long, remove some news items
        return format_telegram_message(entry, news_items[:3])
    
    return message


def test_message_format(message: str) -> bool:
    """Test if message format is valid"""
    # Check for common formatting issues
    issues = []
    
    # Check unescaped characters
    unescaped_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    for char in unescaped_chars:
        if re.search(f'(?<!\\\\){re.escape(char)}', message):
            # Check if it's part of a valid markdown construct
            if not (char in ['*', '_'] and re.search(f'(?<!\\\\){re.escape(char)}[^{re.escape(char)}]+(?<!\\\\){re.escape(char)}', message)):
                issues.append(f"Unescaped {char}")
    
    # Check balanced markdown
    for marker in ['*', '_', '`']:
        escaped_marker = f'\\{marker}'
        count = message.count(marker) - message.count(escaped_marker)
        if count % 2 != 0:
            issues.append(f"Unbalanced {marker}")
    
    if issues:
        logger.warning(f"Message format issues: {', '.join(issues)}")
        return False
    
    return True


def main():
    """Main function with improved error handling"""
    # Validate environment variables
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set")
        return
    
    if not TELEGRAM_CHANNEL_ID:
        logger.error("TELEGRAM_CHANNEL_ID not set")
        return
    
    try:
        logger.info(f"Fetching RSS feed from {RSS_URL}")
        feed = feedparser.parse(RSS_URL)
        
        # Check for feed errors
        if feed.bozo:
            logger.warning(f"Feed parsing issues: {feed.bozo_exception}")
        
        if not feed.entries:
            logger.error("No entries found in RSS feed")
            send_telegram_message(
                "⚠️ No posts found in AI news feed\\. Check [news\\.smol\\.ai](https://news.smol.ai) directly\\.",
                parse_mode='MarkdownV2'
            )
            return
        
        # Get recent posts
        recent_posts = [entry for entry in feed.entries if is_recent_post(entry, hours=25)]
        
        if not recent_posts:
            # Send the latest post if no recent ones
            recent_posts = [feed.entries[0]]
            logger.info("No recent posts found, using latest post")
        
        logger.info(f"Processing {len(recent_posts)} post(s)")
        
        # Process posts (limit to avoid spam)
        for i, post in enumerate(recent_posts[:2]):
            try:
                title = post.get('title', 'AI News Update')
                content = post.get('summary', post.get('description', ''))
                
                logger.info(f"Processing: {title}")
                
                # Extract news items
                news_items = extract_news_items(content, max_items=5)
                logger.info(f"Extracted {len(news_items)} news items")
                
                # Format message
                message = format_telegram_message(post, news_items)
                
                # Test message format
                if not test_message_format(message):
                    logger.warning("Message format issues detected, sending with HTML instead")
                    # Convert to HTML as fallback
                    message = message.replace('\\', '')
                    message = message.replace('*', '<b>').replace('*', '</b>')
                    message = message.replace('_', '<i>').replace('_', '</i>')
                    if send_telegram_message(message, parse_mode='HTML'):
                        logger.info("Message sent successfully with HTML")
                    else:
                        # Last resort: plain text
                        plain_message = clean_html(message)
                        send_telegram_message(plain_message, parse_mode=None)
                else:
                    # Send with MarkdownV2
                    if send_telegram_message(message):
                        logger.info("Message sent successfully")
                    else:
                        logger.error("Failed to send message")
                
                # Rate limiting between messages
                if i < len(recent_posts) - 1:
                    time.sleep(2)
                    
            except Exception as e:
                logger.error(f"Error processing post '{title}': {e}", exc_info=True)
                # Send error notification
                error_msg = f"⚠️ Error processing post: {escape_markdown_v2(str(e)[:100])}"
                send_telegram_message(error_msg, parse_mode='MarkdownV2')
        
        logger.info("Daily update completed successfully!")
        
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        # Try to send error notification
        try:
            error_msg = f"⚠️ Bot error: {escape_markdown_v2(str(e)[:200])}"
            send_telegram_message(error_msg, parse_mode='MarkdownV2')
        except:
            pass


if __name__ == "__main__":
    main(), '', date_str)
    date_str_no_tz = re.sub(r'\s*-\d{4}


def is_recent_post(entry: dict, hours: int = 25) -> bool:
    """Check if post is from the last N hours"""
    published_str = entry.get('published', entry.get('updated', ''))
    
    if not published_str:
        # If no date, assume it's recent
        return True
    
    published_date = parse_rss_date(published_str)
    if published_date:
        cutoff_date = datetime.now() - timedelta(hours=hours)
        return published_date > cutoff_date
    
    # If we can't parse date, assume it's recent
    return True


def clean_html(text: str) -> str:
    """Remove HTML tags and decode entities"""
    import html
    
    # Remove HTML tags
    text = re.sub(r'<[^>]+>', '', text)
    
    # Decode HTML entities
    text = html.unescape(text)
    
    # Clean up extra whitespace
    text = re.sub(r'\s+', ' ', text)
    
    return text.strip()


def extract_url_from_text(text: str) -> Optional[str]:
    """Extract the first URL from text"""
    url_pattern = r'https?://[^\s\)<>\[\]]+(?:[^\s\)<>\[\]]*[^\s\)<>\[\].,;:!?\'"»])?'
    match = re.search(url_pattern, text)
    return match.group(0) if match else None


def extract_news_items(content: str, max_items: int = 5) -> List[Dict[str, str]]:
    """Extract news items with improved pattern matching"""
    content = clean_html(content)
    news_items = []
    
    # Split by common delimiters
    lines = re.split(r'\n|(?<=[.!?])\s+(?=[A-Z])', content)
    
    # Keywords that indicate news
    action_keywords = [
        'announced', 'released', 'launched', 'introduced', 'unveiled',
        'debuted', 'published', 'acquired', 'raised', 'secured',
        'partnered', 'collaborated', 'achieved', 'reached', 'surpassed',
        'developed', 'created', 'built', 'deployed', 'updated'
    ]
    
    # Company/product patterns
    company_pattern = r'\b(?:' + '|'.join([
        'OpenAI', 'Anthropic', 'Google', 'Microsoft', 'Meta', 'Apple',
        'Amazon', 'NVIDIA', 'Tesla', 'DeepMind', 'Stability AI',
        'Hugging Face', 'Mistral', 'Cohere', 'Inflection', 'Character\.AI',
        'Midjourney', 'RunwayML', 'Perplexity', 'Claude', 'ChatGPT',
        'GPT-\d+', 'Gemini', 'LLaMA', 'DALL-E', 'Copilot', 'Bard'
    ]) + r')\b'
    
    seen_items = set()
    
    for line in lines:
        line = line.strip()
        
        # Skip short lines or duplicates
        if len(line) < 30 or line in seen_items:
            continue
        
        # Check if line contains relevant keywords
        line_lower = line.lower()
        has_action = any(keyword in line_lower for keyword in action_keywords)
        has_company = re.search(company_pattern, line, re.IGNORECASE)
        
        # Score the line
        score = 0
        if has_action:
            score += 2
        if has_company:
            score += 2
        if re.match(r'^[-•*]\s*', line):  # Bullet point
            score += 1
        if re.match(r'^\d+\.\s*', line):  # Numbered list
            score += 1
        
        if score >= 2:  # Threshold for inclusion
            # Clean the line
            clean_line = re.sub(r'^[-•*]\s*', '', line)
            clean_line = re.sub(r'^\d+\.\s*', '', clean_line)
            
            # Extract URL if present
            url = extract_url_from_text(clean_line)
            
            news_items.append({
                'text': clean_line,
                'url': url,
                'score': score
            })
            seen_items.add(line)
    
    # Sort by score and return top items
    news_items.sort(key=lambda x: x['score'], reverse=True)
    return news_items[:max_items]


def create_punchy_summary(text: str, max_length: int = 80) -> str:
    """Create a concise summary of news item"""
    # Try to extract key components
    patterns = [
        # Company + action + product/detail
        r'([A-Z][a-zA-Z\s&]+?)\s+(announced|released|launched|introduced|unveiled|acquired|raised|secured)\s+(.{10,50})',
        # Model/Product name pattern
        r'([A-Z][a-zA-Z0-9\s-]+?)\s+(is|are|was|were|has|have)\s+(.{10,50})',
        # Achievement pattern
        r'(.{10,30})\s+(reached|achieved|surpassed|hit)\s+(.{10,30})',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            summary = ' '.join(match.groups())
            if len(summary) <= max_length:
                return summary
    
    # Fallback: smart truncation
    if len(text) <= max_length:
        return text
    
    # Try to break at sentence boundary
    sentences = re.split(r'[.!?]', text)
    if sentences and len(sentences[0]) <= max_length:
        return sentences[0].strip()
    
    # Last resort: truncate at word boundary
    words = text.split()
    summary = ""
    for word in words:
        if len(summary) + len(word) + 1 <= max_length - 3:
            summary += word + " "
        else:
            break
    
    return summary.strip() + "..."


def format_telegram_message(entry: dict, news_items: List[Dict[str, str]]) -> str:
    """Format message for Telegram with MarkdownV2"""
    title = entry.get('title', 'AI News Update')
    link = entry.get('link', '')
    
    # Build message parts
    parts = []
    
    # Header with emoji and title
    escaped_title = escape_markdown_v2(title)
    parts.append(f"🤖 *{escaped_title}*")
    parts.append("")  # Empty line
    
    if news_items:
        parts.append("📰 *Top AI News:*")
        parts.append("")
        
        for i, item in enumerate(news_items[:5], 1):
            summary = create_punchy_summary(item['text'])
            escaped_summary = escape_markdown_v2(summary)
            
            # Add numbered item
            parts.append(f"{i}\\. {escaped_summary}")
            
            # Add link if available
            if item.get('url'):
                escaped_url = escape_markdown_v2(item['url'])
                parts.append(f"   🔗 [Link]({escaped_url})")
            
            parts.append("")  # Empty line between items
    else:
        # Fallback content
        summary = entry.get('summary', entry.get('description', ''))
        if summary:
            summary = clean_html(summary)
            if len(summary) > 200:
                summary = summary[:197] + "..."
            escaped_summary = escape_markdown_v2(summary)
            parts.append(escaped_summary)
            parts.append("")
    
    # Footer with read more link
    if link:
        escaped_link = escape_markdown_v2(link)
        parts.append(f"📄 [Read full post]({escaped_link})")
    
    # Join all parts
    message = '\n'.join(parts)
    
    # Final length check
    if len(message) > TELEGRAM_MAX_LENGTH - 100:
        # If still too long, remove some news items
        return format_telegram_message(entry, news_items[:3])
    
    return message


def test_message_format(message: str) -> bool:
    """Test if message format is valid"""
    # Check for common formatting issues
    issues = []
    
    # Check unescaped characters
    unescaped_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    for char in unescaped_chars:
        if re.search(f'(?<!\\\\){re.escape(char)}', message):
            # Check if it's part of a valid markdown construct
            if not (char in ['*', '_'] and re.search(f'(?<!\\\\){re.escape(char)}[^{re.escape(char)}]+(?<!\\\\){re.escape(char)}', message)):
                issues.append(f"Unescaped {char}")
    
    # Check balanced markdown
    for marker in ['*', '_', '`']:
        escaped_marker = f'\\{marker}'
        count = message.count(marker) - message.count(escaped_marker)
        if count % 2 != 0:
            issues.append(f"Unbalanced {marker}")
    
    if issues:
        logger.warning(f"Message format issues: {', '.join(issues)}")
        return False
    
    return True


def main():
    """Main function with improved error handling"""
    # Validate environment variables
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set")
        return
    
    if not TELEGRAM_CHANNEL_ID:
        logger.error("TELEGRAM_CHANNEL_ID not set")
        return
    
    try:
        logger.info(f"Fetching RSS feed from {RSS_URL}")
        feed = feedparser.parse(RSS_URL)
        
        # Check for feed errors
        if feed.bozo:
            logger.warning(f"Feed parsing issues: {feed.bozo_exception}")
        
        if not feed.entries:
            logger.error("No entries found in RSS feed")
            send_telegram_message(
                "⚠️ No posts found in AI news feed\\. Check [news\\.smol\\.ai](https://news.smol.ai) directly\\.",
                parse_mode='MarkdownV2'
            )
            return
        
        # Get recent posts
        recent_posts = [entry for entry in feed.entries if is_recent_post(entry, hours=25)]
        
        if not recent_posts:
            # Send the latest post if no recent ones
            recent_posts = [feed.entries[0]]
            logger.info("No recent posts found, using latest post")
        
        logger.info(f"Processing {len(recent_posts)} post(s)")
        
        # Process posts (limit to avoid spam)
        for i, post in enumerate(recent_posts[:2]):
            try:
                title = post.get('title', 'AI News Update')
                content = post.get('summary', post.get('description', ''))
                
                logger.info(f"Processing: {title}")
                
                # Extract news items
                news_items = extract_news_items(content, max_items=5)
                logger.info(f"Extracted {len(news_items)} news items")
                
                # Format message
                message = format_telegram_message(post, news_items)
                
                # Test message format
                if not test_message_format(message):
                    logger.warning("Message format issues detected, sending with HTML instead")
                    # Convert to HTML as fallback
                    message = message.replace('\\', '')
                    message = message.replace('*', '<b>').replace('*', '</b>')
                    message = message.replace('_', '<i>').replace('_', '</i>')
                    if send_telegram_message(message, parse_mode='HTML'):
                        logger.info("Message sent successfully with HTML")
                    else:
                        # Last resort: plain text
                        plain_message = clean_html(message)
                        send_telegram_message(plain_message, parse_mode=None)
                else:
                    # Send with MarkdownV2
                    if send_telegram_message(message):
                        logger.info("Message sent successfully")
                    else:
                        logger.error("Failed to send message")
                
                # Rate limiting between messages
                if i < len(recent_posts) - 1:
                    time.sleep(2)
                    
            except Exception as e:
                logger.error(f"Error processing post '{title}': {e}", exc_info=True)
                # Send error notification
                error_msg = f"⚠️ Error processing post: {escape_markdown_v2(str(e)[:100])}"
                send_telegram_message(error_msg, parse_mode='MarkdownV2')
        
        logger.info("Daily update completed successfully!")
        
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        # Try to send error notification
        try:
            error_msg = f"⚠️ Bot error: {escape_markdown_v2(str(e)[:200])}"
            send_telegram_message(error_msg, parse_mode='MarkdownV2')
        except:
            pass


if __name__ == "__main__":
    main(), '', date_str_no_tz)
    date_str_no_tz = re.sub(r'\s*[A-Z]{3,4}


def is_recent_post(entry: dict, hours: int = 25) -> bool:
    """Check if post is from the last N hours"""
    published_str = entry.get('published', entry.get('updated', ''))
    
    if not published_str:
        # If no date, assume it's recent
        return True
    
    published_date = parse_rss_date(published_str)
    if published_date:
        cutoff_date = datetime.now() - timedelta(hours=hours)
        return published_date > cutoff_date
    
    # If we can't parse date, assume it's recent
    return True


def clean_html(text: str) -> str:
    """Remove HTML tags and decode entities"""
    import html
    
    # Remove HTML tags
    text = re.sub(r'<[^>]+>', '', text)
    
    # Decode HTML entities
    text = html.unescape(text)
    
    # Clean up extra whitespace
    text = re.sub(r'\s+', ' ', text)
    
    return text.strip()


def extract_url_from_text(text: str) -> Optional[str]:
    """Extract the first URL from text"""
    url_pattern = r'https?://[^\s\)<>\[\]]+(?:[^\s\)<>\[\]]*[^\s\)<>\[\].,;:!?\'"»])?'
    match = re.search(url_pattern, text)
    return match.group(0) if match else None


def extract_news_items(content: str, max_items: int = 5) -> List[Dict[str, str]]:
    """Extract news items with improved pattern matching"""
    content = clean_html(content)
    news_items = []
    
    # Split by common delimiters
    lines = re.split(r'\n|(?<=[.!?])\s+(?=[A-Z])', content)
    
    # Keywords that indicate news
    action_keywords = [
        'announced', 'released', 'launched', 'introduced', 'unveiled',
        'debuted', 'published', 'acquired', 'raised', 'secured',
        'partnered', 'collaborated', 'achieved', 'reached', 'surpassed',
        'developed', 'created', 'built', 'deployed', 'updated'
    ]
    
    # Company/product patterns
    company_pattern = r'\b(?:' + '|'.join([
        'OpenAI', 'Anthropic', 'Google', 'Microsoft', 'Meta', 'Apple',
        'Amazon', 'NVIDIA', 'Tesla', 'DeepMind', 'Stability AI',
        'Hugging Face', 'Mistral', 'Cohere', 'Inflection', 'Character\.AI',
        'Midjourney', 'RunwayML', 'Perplexity', 'Claude', 'ChatGPT',
        'GPT-\d+', 'Gemini', 'LLaMA', 'DALL-E', 'Copilot', 'Bard'
    ]) + r')\b'
    
    seen_items = set()
    
    for line in lines:
        line = line.strip()
        
        # Skip short lines or duplicates
        if len(line) < 30 or line in seen_items:
            continue
        
        # Check if line contains relevant keywords
        line_lower = line.lower()
        has_action = any(keyword in line_lower for keyword in action_keywords)
        has_company = re.search(company_pattern, line, re.IGNORECASE)
        
        # Score the line
        score = 0
        if has_action:
            score += 2
        if has_company:
            score += 2
        if re.match(r'^[-•*]\s*', line):  # Bullet point
            score += 1
        if re.match(r'^\d+\.\s*', line):  # Numbered list
            score += 1
        
        if score >= 2:  # Threshold for inclusion
            # Clean the line
            clean_line = re.sub(r'^[-•*]\s*', '', line)
            clean_line = re.sub(r'^\d+\.\s*', '', clean_line)
            
            # Extract URL if present
            url = extract_url_from_text(clean_line)
            
            news_items.append({
                'text': clean_line,
                'url': url,
                'score': score
            })
            seen_items.add(line)
    
    # Sort by score and return top items
    news_items.sort(key=lambda x: x['score'], reverse=True)
    return news_items[:max_items]


def create_punchy_summary(text: str, max_length: int = 80) -> str:
    """Create a concise summary of news item"""
    # Try to extract key components
    patterns = [
        # Company + action + product/detail
        r'([A-Z][a-zA-Z\s&]+?)\s+(announced|released|launched|introduced|unveiled|acquired|raised|secured)\s+(.{10,50})',
        # Model/Product name pattern
        r'([A-Z][a-zA-Z0-9\s-]+?)\s+(is|are|was|were|has|have)\s+(.{10,50})',
        # Achievement pattern
        r'(.{10,30})\s+(reached|achieved|surpassed|hit)\s+(.{10,30})',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            summary = ' '.join(match.groups())
            if len(summary) <= max_length:
                return summary
    
    # Fallback: smart truncation
    if len(text) <= max_length:
        return text
    
    # Try to break at sentence boundary
    sentences = re.split(r'[.!?]', text)
    if sentences and len(sentences[0]) <= max_length:
        return sentences[0].strip()
    
    # Last resort: truncate at word boundary
    words = text.split()
    summary = ""
    for word in words:
        if len(summary) + len(word) + 1 <= max_length - 3:
            summary += word + " "
        else:
            break
    
    return summary.strip() + "..."


def format_telegram_message(entry: dict, news_items: List[Dict[str, str]]) -> str:
    """Format message for Telegram with MarkdownV2"""
    title = entry.get('title', 'AI News Update')
    link = entry.get('link', '')
    
    # Build message parts
    parts = []
    
    # Header with emoji and title
    escaped_title = escape_markdown_v2(title)
    parts.append(f"🤖 *{escaped_title}*")
    parts.append("")  # Empty line
    
    if news_items:
        parts.append("📰 *Top AI News:*")
        parts.append("")
        
        for i, item in enumerate(news_items[:5], 1):
            summary = create_punchy_summary(item['text'])
            escaped_summary = escape_markdown_v2(summary)
            
            # Add numbered item
            parts.append(f"{i}\\. {escaped_summary}")
            
            # Add link if available
            if item.get('url'):
                escaped_url = escape_markdown_v2(item['url'])
                parts.append(f"   🔗 [Link]({escaped_url})")
            
            parts.append("")  # Empty line between items
    else:
        # Fallback content
        summary = entry.get('summary', entry.get('description', ''))
        if summary:
            summary = clean_html(summary)
            if len(summary) > 200:
                summary = summary[:197] + "..."
            escaped_summary = escape_markdown_v2(summary)
            parts.append(escaped_summary)
            parts.append("")
    
    # Footer with read more link
    if link:
        escaped_link = escape_markdown_v2(link)
        parts.append(f"📄 [Read full post]({escaped_link})")
    
    # Join all parts
    message = '\n'.join(parts)
    
    # Final length check
    if len(message) > TELEGRAM_MAX_LENGTH - 100:
        # If still too long, remove some news items
        return format_telegram_message(entry, news_items[:3])
    
    return message


def test_message_format(message: str) -> bool:
    """Test if message format is valid"""
    # Check for common formatting issues
    issues = []
    
    # Check unescaped characters
    unescaped_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    for char in unescaped_chars:
        if re.search(f'(?<!\\\\){re.escape(char)}', message):
            # Check if it's part of a valid markdown construct
            if not (char in ['*', '_'] and re.search(f'(?<!\\\\){re.escape(char)}[^{re.escape(char)}]+(?<!\\\\){re.escape(char)}', message)):
                issues.append(f"Unescaped {char}")
    
    # Check balanced markdown
    for marker in ['*', '_', '`']:
        escaped_marker = f'\\{marker}'
        count = message.count(marker) - message.count(escaped_marker)
        if count % 2 != 0:
            issues.append(f"Unbalanced {marker}")
    
    if issues:
        logger.warning(f"Message format issues: {', '.join(issues)}")
        return False
    
    return True


def main():
    """Main function with improved error handling"""
    # Validate environment variables
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set")
        return
    
    if not TELEGRAM_CHANNEL_ID:
        logger.error("TELEGRAM_CHANNEL_ID not set")
        return
    
    try:
        logger.info(f"Fetching RSS feed from {RSS_URL}")
        feed = feedparser.parse(RSS_URL)
        
        # Check for feed errors
        if feed.bozo:
            logger.warning(f"Feed parsing issues: {feed.bozo_exception}")
        
        if not feed.entries:
            logger.error("No entries found in RSS feed")
            send_telegram_message(
                "⚠️ No posts found in AI news feed\\. Check [news\\.smol\\.ai](https://news.smol.ai) directly\\.",
                parse_mode='MarkdownV2'
            )
            return
        
        # Get recent posts
        recent_posts = [entry for entry in feed.entries if is_recent_post(entry, hours=25)]
        
        if not recent_posts:
            # Send the latest post if no recent ones
            recent_posts = [feed.entries[0]]
            logger.info("No recent posts found, using latest post")
        
        logger.info(f"Processing {len(recent_posts)} post(s)")
        
        # Process posts (limit to avoid spam)
        for i, post in enumerate(recent_posts[:2]):
            try:
                title = post.get('title', 'AI News Update')
                content = post.get('summary', post.get('description', ''))
                
                logger.info(f"Processing: {title}")
                
                # Extract news items
                news_items = extract_news_items(content, max_items=5)
                logger.info(f"Extracted {len(news_items)} news items")
                
                # Format message
                message = format_telegram_message(post, news_items)
                
                # Test message format
                if not test_message_format(message):
                    logger.warning("Message format issues detected, sending with HTML instead")
                    # Convert to HTML as fallback
                    message = message.replace('\\', '')
                    message = message.replace('*', '<b>').replace('*', '</b>')
                    message = message.replace('_', '<i>').replace('_', '</i>')
                    if send_telegram_message(message, parse_mode='HTML'):
                        logger.info("Message sent successfully with HTML")
                    else:
                        # Last resort: plain text
                        plain_message = clean_html(message)
                        send_telegram_message(plain_message, parse_mode=None)
                else:
                    # Send with MarkdownV2
                    if send_telegram_message(message):
                        logger.info("Message sent successfully")
                    else:
                        logger.error("Failed to send message")
                
                # Rate limiting between messages
                if i < len(recent_posts) - 1:
                    time.sleep(2)
                    
            except Exception as e:
                logger.error(f"Error processing post '{title}': {e}", exc_info=True)
                # Send error notification
                error_msg = f"⚠️ Error processing post: {escape_markdown_v2(str(e)[:100])}"
                send_telegram_message(error_msg, parse_mode='MarkdownV2')
        
        logger.info("Daily update completed successfully!")
        
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        # Try to send error notification
        try:
            error_msg = f"⚠️ Bot error: {escape_markdown_v2(str(e)[:200])}"
            send_telegram_message(error_msg, parse_mode='MarkdownV2')
        except:
            pass


if __name__ == "__main__":
    main(), '', date_str_no_tz)
    
    for fmt in date_formats:
        try:
            return datetime.strptime(date_str_no_tz.strip(), fmt.replace(' %z', '').replace(' %Z', '').replace('%z', '').replace('Z', ''))
        except ValueError:
            continue
    
    logger.debug(f"Could not parse date: {date_str}")
    return None


def is_recent_post(entry: dict, hours: int = 25) -> bool:
    """Check if post is from the last N hours"""
    published_str = entry.get('published', entry.get('updated', ''))
    
    if not published_str:
        # If no date, assume it's recent
        return True
    
    published_date = parse_rss_date(published_str)
    if published_date:
        cutoff_date = datetime.now() - timedelta(hours=hours)
        return published_date > cutoff_date
    
    # If we can't parse date, assume it's recent
    return True


def clean_html(text: str) -> str:
    """Remove HTML tags and decode entities"""
    import html
    
    # Remove HTML tags
    text = re.sub(r'<[^>]+>', '', text)
    
    # Decode HTML entities
    text = html.unescape(text)
    
    # Clean up extra whitespace
    text = re.sub(r'\s+', ' ', text)
    
    return text.strip()


def extract_url_from_text(text: str) -> Optional[str]:
    """Extract the first URL from text"""
    url_pattern = r'https?://[^\s\)<>\[\]]+(?:[^\s\)<>\[\]]*[^\s\)<>\[\].,;:!?\'"»])?'
    match = re.search(url_pattern, text)
    return match.group(0) if match else None


def extract_news_items(content: str, max_items: int = 5) -> List[Dict[str, str]]:
    """Extract news items with improved pattern matching"""
    content = clean_html(content)
    news_items = []
    
    # Split by common delimiters
    lines = re.split(r'\n|(?<=[.!?])\s+(?=[A-Z])', content)
    
    # Keywords that indicate news
    action_keywords = [
        'announced', 'released', 'launched', 'introduced', 'unveiled',
        'debuted', 'published', 'acquired', 'raised', 'secured',
        'partnered', 'collaborated', 'achieved', 'reached', 'surpassed',
        'developed', 'created', 'built', 'deployed', 'updated'
    ]
    
    # Company/product patterns
    company_pattern = r'\b(?:' + '|'.join([
        'OpenAI', 'Anthropic', 'Google', 'Microsoft', 'Meta', 'Apple',
        'Amazon', 'NVIDIA', 'Tesla', 'DeepMind', 'Stability AI',
        'Hugging Face', 'Mistral', 'Cohere', 'Inflection', 'Character\.AI',
        'Midjourney', 'RunwayML', 'Perplexity', 'Claude', 'ChatGPT',
        'GPT-\d+', 'Gemini', 'LLaMA', 'DALL-E', 'Copilot', 'Bard'
    ]) + r')\b'
    
    seen_items = set()
    
    for line in lines:
        line = line.strip()
        
        # Skip short lines or duplicates
        if len(line) < 30 or line in seen_items:
            continue
        
        # Check if line contains relevant keywords
        line_lower = line.lower()
        has_action = any(keyword in line_lower for keyword in action_keywords)
        has_company = re.search(company_pattern, line, re.IGNORECASE)
        
        # Score the line
        score = 0
        if has_action:
            score += 2
        if has_company:
            score += 2
        if re.match(r'^[-•*]\s*', line):  # Bullet point
            score += 1
        if re.match(r'^\d+\.\s*', line):  # Numbered list
            score += 1
        
        if score >= 2:  # Threshold for inclusion
            # Clean the line
            clean_line = re.sub(r'^[-•*]\s*', '', line)
            clean_line = re.sub(r'^\d+\.\s*', '', clean_line)
            
            # Extract URL if present
            url = extract_url_from_text(clean_line)
            
            news_items.append({
                'text': clean_line,
                'url': url,
                'score': score
            })
            seen_items.add(line)
    
    # Sort by score and return top items
    news_items.sort(key=lambda x: x['score'], reverse=True)
    return news_items[:max_items]


def create_punchy_summary(text: str, max_length: int = 80) -> str:
    """Create a concise summary of news item"""
    # Try to extract key components
    patterns = [
        # Company + action + product/detail
        r'([A-Z][a-zA-Z\s&]+?)\s+(announced|released|launched|introduced|unveiled|acquired|raised|secured)\s+(.{10,50})',
        # Model/Product name pattern
        r'([A-Z][a-zA-Z0-9\s-]+?)\s+(is|are|was|were|has|have)\s+(.{10,50})',
        # Achievement pattern
        r'(.{10,30})\s+(reached|achieved|surpassed|hit)\s+(.{10,30})',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            summary = ' '.join(match.groups())
            if len(summary) <= max_length:
                return summary
    
    # Fallback: smart truncation
    if len(text) <= max_length:
        return text
    
    # Try to break at sentence boundary
    sentences = re.split(r'[.!?]', text)
    if sentences and len(sentences[0]) <= max_length:
        return sentences[0].strip()
    
    # Last resort: truncate at word boundary
    words = text.split()
    summary = ""
    for word in words:
        if len(summary) + len(word) + 1 <= max_length - 3:
            summary += word + " "
        else:
            break
    
    return summary.strip() + "..."


def format_telegram_message(entry: dict, news_items: List[Dict[str, str]]) -> str:
    """Format message for Telegram with MarkdownV2"""
    title = entry.get('title', 'AI News Update')
    link = entry.get('link', '')
    
    # Build message parts
    parts = []
    
    # Header with emoji and title
    escaped_title = escape_markdown_v2(title)
    parts.append(f"🤖 *{escaped_title}*")
    parts.append("")  # Empty line
    
    if news_items:
        parts.append("📰 *Top AI News:*")
        parts.append("")
        
        for i, item in enumerate(news_items[:5], 1):
            summary = create_punchy_summary(item['text'])
            escaped_summary = escape_markdown_v2(summary)
            
            # Add numbered item
            parts.append(f"{i}\\. {escaped_summary}")
            
            # Add link if available
            if item.get('url'):
                escaped_url = escape_markdown_v2(item['url'])
                parts.append(f"   🔗 [Link]({escaped_url})")
            
            parts.append("")  # Empty line between items
    else:
        # Fallback content
        summary = entry.get('summary', entry.get('description', ''))
        if summary:
            summary = clean_html(summary)
            if len(summary) > 200:
                summary = summary[:197] + "..."
            escaped_summary = escape_markdown_v2(summary)
            parts.append(escaped_summary)
            parts.append("")
    
    # Footer with read more link
    if link:
        escaped_link = escape_markdown_v2(link)
        parts.append(f"📄 [Read full post]({escaped_link})")
    
    # Join all parts
    message = '\n'.join(parts)
    
    # Final length check
    if len(message) > TELEGRAM_MAX_LENGTH - 100:
        # If still too long, remove some news items
        return format_telegram_message(entry, news_items[:3])
    
    return message


def test_message_format(message: str) -> bool:
    """Test if message format is valid"""
    # Check for common formatting issues
    issues = []
    
    # Check unescaped characters
    unescaped_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    for char in unescaped_chars:
        if re.search(f'(?<!\\\\){re.escape(char)}', message):
            # Check if it's part of a valid markdown construct
            if not (char in ['*', '_'] and re.search(f'(?<!\\\\){re.escape(char)}[^{re.escape(char)}]+(?<!\\\\){re.escape(char)}', message)):
                issues.append(f"Unescaped {char}")
    
    # Check balanced markdown
    for marker in ['*', '_', '`']:
        escaped_marker = f'\\{marker}'
        count = message.count(marker) - message.count(escaped_marker)
        if count % 2 != 0:
            issues.append(f"Unbalanced {marker}")
    
    if issues:
        logger.warning(f"Message format issues: {', '.join(issues)}")
        return False
    
    return True


def main():
    """Main function with improved error handling"""
    # Validate environment variables
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set")
        return
    
    if not TELEGRAM_CHANNEL_ID:
        logger.error("TELEGRAM_CHANNEL_ID not set")
        return
    
    try:
        logger.info(f"Fetching RSS feed from {RSS_URL}")
        feed = feedparser.parse(RSS_URL)
        
        # Check for feed errors
        if feed.bozo:
            logger.warning(f"Feed parsing issues: {feed.bozo_exception}")
        
        if not feed.entries:
            logger.error("No entries found in RSS feed")
            send_telegram_message(
                "⚠️ No posts found in AI news feed\\. Check [news\\.smol\\.ai](https://news.smol.ai) directly\\.",
                parse_mode='MarkdownV2'
            )
            return
        
        # Get recent posts
        recent_posts = [entry for entry in feed.entries if is_recent_post(entry, hours=25)]
        
        if not recent_posts:
            # Send the latest post if no recent ones
            recent_posts = [feed.entries[0]]
            logger.info("No recent posts found, using latest post")
        
        logger.info(f"Processing {len(recent_posts)} post(s)")
        
        # Process posts (limit to avoid spam)
        for i, post in enumerate(recent_posts[:2]):
            try:
                title = post.get('title', 'AI News Update')
                content = post.get('summary', post.get('description', ''))
                
                logger.info(f"Processing: {title}")
                
                # Extract news items
                news_items = extract_news_items(content, max_items=5)
                logger.info(f"Extracted {len(news_items)} news items")
                
                # Format message
                message = format_telegram_message(post, news_items)
                
                # Test message format
                if not test_message_format(message):
                    logger.warning("Message format issues detected, sending with HTML instead")
                    # Convert to HTML as fallback
                    message = message.replace('\\', '')
                    message = message.replace('*', '<b>').replace('*', '</b>')
                    message = message.replace('_', '<i>').replace('_', '</i>')
                    if send_telegram_message(message, parse_mode='HTML'):
                        logger.info("Message sent successfully with HTML")
                    else:
                        # Last resort: plain text
                        plain_message = clean_html(message)
                        send_telegram_message(plain_message, parse_mode=None)
                else:
                    # Send with MarkdownV2
                    if send_telegram_message(message):
                        logger.info("Message sent successfully")
                    else:
                        logger.error("Failed to send message")
                
                # Rate limiting between messages
                if i < len(recent_posts) - 1:
                    time.sleep(2)
                    
            except Exception as e:
                logger.error(f"Error processing post '{title}': {e}", exc_info=True)
                # Send error notification
                error_msg = f"⚠️ Error processing post: {escape_markdown_v2(str(e)[:100])}"
                send_telegram_message(error_msg, parse_mode='MarkdownV2')
        
        logger.info("Daily update completed successfully!")
        
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        # Try to send error notification
        try:
            error_msg = f"⚠️ Bot error: {escape_markdown_v2(str(e)[:200])}"
            send_telegram_message(error_msg, parse_mode='MarkdownV2')
        except:
            pass


if __name__ == "__main__":
    main()
