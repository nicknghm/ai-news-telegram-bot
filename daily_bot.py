def create_punchy_summary(text: str, max_length: int = 120) -> str:
    """Create a concise summary of news item without cutting off important parts"""
    # Clean up the text first
    text = text.strip()
    
    # If already short enough, return as is
    if len(text) <= max_length:
        return text
    
    # First, try to identify if this is a complete news item
    # Look for company names at the beginning
    company_pattern = r'^((?:' + '|'.join([
        'OpenAI', 'Anthropic', 'Google', 'Microsoft', 'Meta', 'Apple',
        'Amazon', 'NVIDIA', 'Tesla', 'DeepMind', 'Stability AI',
        'Hugging Face', 'HuggingFace', 'Mistral', 'Cohere', 'Inflection',
        'Midjourney', 'RunwayML', 'Perplexity', 'Meanwhile', 'Moonshot AI',
        'xAI', 'Groq', 'Cerebras', 'Together AI', 'Character\.AI',
        r'[A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)*'  # Generic company name pattern
    ]) + r'))\b'
    
    # Check if text starts with a company name or important keyword
    company_match = re.match(company_pattern, text, re.IGNORECASE)
    
    # Try to extract key components for specific patterns
    patterns = [
        # Company + action + product/detail
        (r'^([^,]+(?:announced|released|launched|introduced|unveiled|has released)[^,]+)', True),
        # Product release pattern
        (r'^([^,]+(?:is now|now|is)\s+(?:available|open source|released|launched)[^,]*)', True),
        # Achievement/milestone pattern
        (r'^([^,]+(?:reached|achieved|surpassed|hit|proved|proves)[^,]+)', True),
        # Funding pattern
        (r'^([^,]+(?:raises|raised|secures|secured)\s+\$[\d\.]+[MBK]?(?:\s*(?:million|billion))?[^,]*)', True),
        # Generic pattern with company at start
        (r'^(' + company_pattern + r'[^.!?]+)', False),
    ]
    
    for pattern, complete in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            summary = match.group(1).strip()
            if len(summary) <= max_length:
                return summary
            elif complete:
                # If it's a complete pattern but too long, try to shorten
                break
    
    # If we have a company name at the start, preserve it
    if company_match:
        company_name = company_match.group(1)
        remaining_text = text[len(company_name):].strip()
        
        # Find the key action in the remaining text
        action_match = re.search(r'(announced|released|launched|introduced|unveiled|raised|secured|partnered|achieved|reached|proves|has released|is now available)', remaining_text, re.IGNORECASE)
        
        if action_match:
            # Include company + action + some context
            action_pos = action_match.start()
            action_end = action_match.end()
            
            # Find the end of the key information (usually at comma, semicolon, or certain keywords)
            end_patterns = [r',', r';', r'\sand\s', r'\swith\s', r'\sfor\s']
            end_pos = len(remaining_text)
            
            for end_pattern in end_patterns:
                match = re.search(end_pattern, remaining_text[action_end:])
                if match:
                    potential_end = action_end + match.start()
                    if potential_end < end_pos:
                        end_pos = potential_end
            
            summary = company_name + ' ' + remaining_text[:end_pos].strip()
            if len(summary) <= max_length:
                return summary
    
    # Smart truncation: try to break at sentence boundary
    if '. ' in text[:max_length]:
        sentences = text.split('. ')
        summary = sentences[0]
        if len(summary) <= max_length:
            return summary + '.'
    
    # Break at comma or other delimiters
    for delimiter in [', ', '; ', ' - ', ' with ', ' for ']:
        if delimiter in text[:max_length]:
            end_pos = text[:max_length].rfind(delimiter)
            if end_pos > max_length * 0.6:  # Only if we're not losing too much
                return text[:end_pos].strip() + '...'
    
    # Last resort: try to find a good word boundary
    # But first, ensure we don't cut off in the middle of important information
    words = text.split()
    
    # If the text starts with a short important phrase, preserve it
    important_start_words = ['Meanwhile', 'Additionally', 'Furthermore', 'However']
    preserve_words = 1
    if words[0] in important_start_words:
        preserve_words = 2
    
    summary = ""
    for i, word in enumerate(words):
        if len(summary) + len(word) + 1 <= max_length - 3:
            summary += word + " "
        elif i >= preserve_words:  # Ensure we include at least the important start
            break
    
    return summary.strip() + "..."import feedparser
import requests
import os
import logging
import time
import re
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
import html

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
        # Keep some buffer for safety
        message = message[:TELEGRAM_MAX_LENGTH - 50] + '\n\n\\.\\.\\.truncated'
    
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
                if "can't parse" in response.text.lower() and parse_mode != None:
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
        '%a, %d %b %Y %H:%M:%S %z',
        '%a, %d %b %Y %H:%M:%S %Z',
        '%Y-%m-%dT%H:%M:%S%z',
        '%Y-%m-%dT%H:%M:%SZ',
        '%Y-%m-%d %H:%M:%S',
        '%Y-%m-%d',
    ]
    
    # Clean up the date string
    date_str_clean = date_str.strip()
    
    for fmt in date_formats:
        try:
            return datetime.strptime(date_str_clean, fmt)
        except ValueError:
            continue
    
    # Try without timezone info if all else fails
    date_str_no_tz = re.sub(r'\s*[+-]\d{4}$', '', date_str_clean)
    date_str_no_tz = re.sub(r'\s*[A-Z]{3,4}$', '', date_str_no_tz)
    
    for fmt in date_formats:
        try:
            fmt_no_tz = fmt.replace(' %z', '').replace(' %Z', '').replace('%z', '').replace('Z', '')
            return datetime.strptime(date_str_no_tz.strip(), fmt_no_tz)
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
        # Make datetime naive for comparison
        if published_date.tzinfo:
            published_date = published_date.replace(tzinfo=None)
        cutoff_date = datetime.now() - timedelta(hours=hours)
        return published_date > cutoff_date
    
    # If we can't parse date, assume it's recent
    return True


def clean_html(text: str) -> str:
    """Remove HTML tags and decode entities"""
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
    
    # More sophisticated line extraction
    lines = []
    
    # First, try to find numbered items more carefully
    # Look for patterns like "1. Company announced..." and capture the full item
    numbered_pattern = r'\d+\.\s*([^\.]+(?:\.[^\.]+)*?)(?=\d+\.|$)'
    numbered_matches = re.findall(numbered_pattern, content, re.MULTILINE | re.DOTALL)
    if numbered_matches:
        lines.extend([match.strip() for match in numbered_matches])
    
    # Also look for bullet points
    bullet_pattern = r'[-•*]\s*([^-•*\n]+(?:\n(?![-•*])[^-•*\n]+)*)'
    bullet_matches = re.findall(bullet_pattern, content)
    if bullet_matches:
        lines.extend([match.strip() for match in bullet_matches])
    
    # If no structured format found, split by sentences more carefully
    if not lines:
        # Split by sentence-ending punctuation followed by space and capital letter
        sentence_splits = re.split(r'(?<=[.!?])\s+(?=[A-Z])', content)
        lines.extend(sentence_splits)
    
    # Also add the full content as one item in case it's all one news item
    lines.append(content)
    
    # Remove duplicates while preserving order
    seen = set()
    unique_lines = []
    for line in lines:
        line = line.strip()
        if line and line not in seen and len(line) > 20:
            seen.add(line)
            unique_lines.append(line)
    
    # Keywords that indicate news
    action_keywords = [
        'announced', 'released', 'launched', 'introduced', 'unveiled',
        'debuted', 'published', 'acquired', 'raised', 'secured',
        'partnered', 'collaborated', 'achieved', 'reached', 'surpassed',
        'developed', 'created', 'built', 'deployed', 'updated',
        'reveals', 'launches', 'announces', 'introduces', 'ships',
        'open-source', 'open source', 'available', 'proves', 'demonstrated'
    ]
    
    # Expanded company/product patterns
    company_pattern = r'\b(?:' + '|'.join([
        'OpenAI', 'Anthropic', 'Google', 'Microsoft', 'Meta', 'Apple',
        'Amazon', 'NVIDIA', 'Tesla', 'DeepMind', 'Stability AI',
        'Hugging Face', 'Mistral', 'Cohere', 'Inflection', 'Character\.AI',
        'Midjourney', 'RunwayML', 'Perplexity', 'Claude', 'ChatGPT',
        'GPT-\d+', 'Gemini', 'LLaMA', 'DALL-E', 'Copilot', 'Bard',
        'HuggingFace', 'SmolLM\d*', 'Groq', 'Cerebras', 'Together AI',
        'Moonshot AI', 'Kimi', 'Meanwhile', 'MoE', 'Mixture-of-Experts',
        'K2', 'Grok-\d+', 'xAI'
    ]) + r')\b'
    
    processed_items = []
    
    for line in unique_lines:
        line = line.strip()
        
        # Skip very short lines
        if len(line) < 30:
            continue
        
        # Check if line contains relevant keywords
        line_lower = line.lower()
        has_action = any(keyword in line_lower for keyword in action_keywords)
        has_company = re.search(company_pattern, line, re.IGNORECASE)
        
        # Look for technical indicators
        has_technical = any(term in line_lower for term in [
            'ai', 'model', 'llm', 'api', 'open source', 'open-source',
            'billion', 'million', 'parameters', 'tokens', 'scale',
            'frontier', 'sota', 'benchmark', 'reasoning'
        ])
        
        # Score the line
        score = 0
        if has_action:
            score += 2
        if has_company:
            score += 3  # Increased weight for company mentions
        if has_technical:
            score += 2
        # Give bonus score if it starts with a capital letter (likely a sentence start)
        if re.match(r'^[A-Z]', line):
            score += 1
        
        if score >= 3:  # Increased threshold
            # Extract URL if present
            url = extract_url_from_text(line)
            
            # Clean the line but preserve the complete sentence
            clean_line = line
            # Only remove list markers from the very beginning
            clean_line = re.sub(r'^[-•*]\s*', '', clean_line)
            clean_line = re.sub(r'^\d+\.\s*', '', clean_line)
            clean_line = clean_line.strip()
            
            # Ensure we have the complete thought
            # If the line seems cut off at the beginning, try to find the full sentence
            if not re.match(r'^[A-Z]', clean_line) or clean_line[0:10].count(' ') < 1:
                # This might be a fragment, skip it
                continue
            
            processed_items.append({
                'text': clean_line,
                'url': url,
                'score': score,
                'original': line
            })
    
    # Sort by score
    processed_items.sort(key=lambda x: x['score'], reverse=True)
    
    # Remove duplicates and fragments
    final_items = []
    for item in processed_items:
        is_duplicate = False
        is_fragment = False
        
        for final_item in final_items:
            # Check if items are too similar
            if (item['text'][:50].lower() == final_item['text'][:50].lower() or
                item['text'] in final_item['text'] or
                final_item['text'] in item['text']):
                is_duplicate = True
                break
        
        # Check if this seems like a complete sentence
        if not re.search(r'[.!?]


def create_punchy_summary(text: str, max_length: int = 100) -> str:
    """Create a concise summary of news item"""
    # Clean up the text first
    text = text.strip()
    
    # If already short enough, return as is
    if len(text) <= max_length:
        return text
    
    # Try to extract key components
    patterns = [
        # Company + action + product/detail
        r'([A-Z][a-zA-Z\s&]+?)\s+(announced|released|launched|introduced|unveiled|acquired|raised|secured)\s+(.{10,60})',
        # Product release pattern
        r'([A-Z][a-zA-Z0-9\s\-\.]+?)\s+(is now|now|is)\s+(available|open source|released|launched)',
        # Funding pattern
        r'([A-Z][a-zA-Z\s&]+?)\s+(raises|raised|secures|secured)\s+(\$[\d\.]+[MBK]?\s*(?:million|billion)?)',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            summary = ' '.join(match.groups())
            if len(summary) <= max_length:
                return summary
    
    # Smart truncation: try to break at sentence boundary
    if '.' in text[:max_length]:
        end_pos = text[:max_length].rfind('.')
        if end_pos > max_length * 0.5:  # Only if we're not losing too much
            return text[:end_pos]
    
    # Break at comma or semicolon
    for delimiter in [',', ';', ' - ']:
        if delimiter in text[:max_length]:
            end_pos = text[:max_length].rfind(delimiter)
            if end_pos > max_length * 0.6:
                return text[:end_pos] + '...'
    
    # Last resort: truncate at word boundary
    words = text.split()
    summary = ""
    for word in words:
        if len(summary) + len(word) + 1 <= max_length - 3:
            summary += word + " "
        else:
            break
    
    return summary.strip() + "..."


def format_telegram_message(entries: List[dict]) -> str:
    """Format a single consolidated message for Telegram with all recent posts"""
    if not entries:
        return "⚠️ No recent AI news found\\."
    
    # Build message parts
    parts = []
    
    # Header - Use HTML format for better compatibility
    parts.append("<b>🤖 AI News Daily Summary</b>")
    parts.append("")  # Empty line
    
    # Process each entry
    all_news_items = []
    
    for entry in entries[:3]:  # Limit to 3 most recent posts
        title = entry.get('title', 'AI News Update')
        content = entry.get('summary', entry.get('description', ''))
        link = entry.get('link', '')
        
        # Extract news items from this entry
        news_items = extract_news_items(content, max_items=5)
        
        # Add source info to each item
        for item in news_items:
            item['source_title'] = title
            item['source_link'] = link
        
        all_news_items.extend(news_items)
    
    # Sort all news items by score and deduplicate
    all_news_items.sort(key=lambda x: x['score'], reverse=True)
    
    # Remove duplicates
    seen_summaries = set()
    unique_items = []
    for item in all_news_items:
        summary_key = item['text'][:50].lower()
        if summary_key not in seen_summaries:
            seen_summaries.add(summary_key)
            unique_items.append(item)
    
    # Take top 7 items
    top_items = unique_items[:7]
    
    if top_items:
        parts.append("<b>📰 Top AI News Items:</b>")
        parts.append("")
        
        for i, item in enumerate(top_items, 1):
            # Get the full text for summary
            full_text = item['text']
            
            # Ensure we have complete sentences
            if not full_text.endswith(('.', '!', '?')):
                full_text += '.'
            
            # Create summary without cutting off company names
            summary = create_punchy_summary(full_text, max_length=120)
            
            # Format the item (no escaping needed for HTML)
            parts.append(f"<b>{i}.</b> {summary}")
            
            # Add link if available
            if item.get('url'):
                parts.append(f'   🔗 <a href="{item["url"]}">Read more</a>')
            
            parts.append("")  # Empty line between items
    else:
        # Fallback if no structured items found
        parts.append("<i>No structured news items found. Check the full posts below.</i>")
        parts.append("")
    
    # Footer section with source links
    parts.append("━━━━━━━━━━━━━━━")
    parts.append("<b>📄 Full Posts:</b>")
    parts.append("")
    
    # Add unique source links
    seen_links = set()
    for entry in entries[:3]:
        link = entry.get('link', '')
        title = entry.get('title', 'Post')
        if link and link not in seen_links:
            seen_links.add(link)
            parts.append(f'• <a href="{link}">{html.escape(title)}</a>')
    
    parts.append("")
    parts.append(f"<i>🕐 Generated: {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}</i>")
    
    # Join all parts
    message = '\n'.join(parts)
    
    # Final length check
    if len(message) > TELEGRAM_MAX_LENGTH - 200:
        # If too long, reduce number of items
        return format_telegram_message(entries[:2])  # Retry with fewer entries
    
    return message


def test_message_format(message: str) -> bool:
    """Test if message format is valid"""
    # Check for common formatting issues
    issues = []
    
    # Check unescaped characters (but skip those in valid markdown constructs)
    # This is a simplified check - in production you might want more sophisticated validation
    
    # Check balanced markdown
    for marker in ['*', '_', '`']:
        # Count unescaped occurrences
        pattern = f'(?<!\\\\){re.escape(marker)}'
        matches = re.findall(pattern, message)
        if len(matches) % 2 != 0:
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
                "<b>⚠️ No posts found in AI news feed.</b>\nCheck <a href='https://news.smol.ai'>news.smol.ai</a> directly.",
                parse_mode='HTML'
            )
            return
        
        # Get recent posts
        recent_posts = [entry for entry in feed.entries if is_recent_post(entry, hours=25)]
        
        if not recent_posts:
            # If no recent posts, take the latest one
            recent_posts = [feed.entries[0]]
            logger.info("No recent posts found, using latest post")
        
        logger.info(f"Found {len(recent_posts)} recent post(s)")
        
        # Create a single consolidated message using HTML format
        message = format_telegram_message(recent_posts)
        
        # Send with HTML format (more reliable than MarkdownV2)
        if send_telegram_message(message, parse_mode='HTML'):
            logger.info("Message sent successfully")
        else:
            logger.error("Failed to send message with HTML")
            # Last resort: plain text
            plain_message = re.sub(r'<[^>]+>', '', message)  # Remove HTML tags
            plain_message = html.unescape(plain_message)  # Decode HTML entities
            if send_telegram_message(plain_message, parse_mode=None):
                logger.info("Message sent as plain text")
            else:
                logger.error("Failed to send message in any format")
        
        logger.info("Daily update completed successfully!")
        
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        # Try to send error notification
        try:
            error_msg = f"<b>⚠️ Bot error:</b> {html.escape(str(e)[:200])}"
            send_telegram_message(error_msg, parse_mode='HTML')
        except:
            pass


if __name__ == "__main__":
    main(), item['text']) and len(item['text']) < 60:
            is_fragment = True
        
        if not is_duplicate and not is_fragment:
            final_items.append(item)
    
    return final_items[:max_items]


def create_punchy_summary(text: str, max_length: int = 100) -> str:
    """Create a concise summary of news item"""
    # Clean up the text first
    text = text.strip()
    
    # If already short enough, return as is
    if len(text) <= max_length:
        return text
    
    # Try to extract key components
    patterns = [
        # Company + action + product/detail
        r'([A-Z][a-zA-Z\s&]+?)\s+(announced|released|launched|introduced|unveiled|acquired|raised|secured)\s+(.{10,60})',
        # Product release pattern
        r'([A-Z][a-zA-Z0-9\s\-\.]+?)\s+(is now|now|is)\s+(available|open source|released|launched)',
        # Funding pattern
        r'([A-Z][a-zA-Z\s&]+?)\s+(raises|raised|secures|secured)\s+(\$[\d\.]+[MBK]?\s*(?:million|billion)?)',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            summary = ' '.join(match.groups())
            if len(summary) <= max_length:
                return summary
    
    # Smart truncation: try to break at sentence boundary
    if '.' in text[:max_length]:
        end_pos = text[:max_length].rfind('.')
        if end_pos > max_length * 0.5:  # Only if we're not losing too much
            return text[:end_pos]
    
    # Break at comma or semicolon
    for delimiter in [',', ';', ' - ']:
        if delimiter in text[:max_length]:
            end_pos = text[:max_length].rfind(delimiter)
            if end_pos > max_length * 0.6:
                return text[:end_pos] + '...'
    
    # Last resort: truncate at word boundary
    words = text.split()
    summary = ""
    for word in words:
        if len(summary) + len(word) + 1 <= max_length - 3:
            summary += word + " "
        else:
            break
    
    return summary.strip() + "..."


def format_telegram_message(entries: List[dict]) -> str:
    """Format a single consolidated message for Telegram with all recent posts"""
    if not entries:
        return "⚠️ No recent AI news found\\."
    
    # Build message parts
    parts = []
    
    # Header
    parts.append("🤖 *AI News Daily Summary*")
    parts.append("")  # Empty line
    
    # Process each entry
    all_news_items = []
    
    for entry in entries[:3]:  # Limit to 3 most recent posts to avoid too long messages
        title = entry.get('title', 'AI News Update')
        content = entry.get('summary', entry.get('description', ''))
        link = entry.get('link', '')
        
        # Extract news items from this entry
        news_items = extract_news_items(content, max_items=5)
        
        # Add source info to each item
        for item in news_items:
            item['source_title'] = title
            item['source_link'] = link
        
        all_news_items.extend(news_items)
    
    # Sort all news items by score and deduplicate
    all_news_items.sort(key=lambda x: x['score'], reverse=True)
    
    # Remove duplicates
    seen_summaries = set()
    unique_items = []
    for item in all_news_items:
        summary_key = item['text'][:50].lower()
        if summary_key not in seen_summaries:
            seen_summaries.add(summary_key)
            unique_items.append(item)
    
    # Take top 7 items
    top_items = unique_items[:7]
    
    if top_items:
        parts.append("📰 *Top AI News Items:*")
        parts.append("")
        
        for i, item in enumerate(top_items, 1):
            summary = create_punchy_summary(item['text'])
            escaped_summary = escape_markdown_v2(summary)
            
            # Add numbered item with better formatting
            parts.append(f"*{i}\\.* {escaped_summary}")
            
            # Add link if available (prefer item URL over source URL)
            if item.get('url'):
                escaped_url = escape_markdown_v2(item['url'])
                parts.append(f"   🔗 [Read more]({escaped_url})")
            
            parts.append("")  # Empty line between items
    
    # Footer section with source links
    parts.append("━━━━━━━━━━━━━━━")
    parts.append("📄 *Full Posts:*")
    parts.append("")
    
    # Add unique source links
    seen_links = set()
    for entry in entries[:3]:
        link = entry.get('link', '')
        title = entry.get('title', 'Post')
        if link and link not in seen_links:
            seen_links.add(link)
            escaped_link = escape_markdown_v2(link)
            escaped_title = escape_markdown_v2(title)
            parts.append(f"• [{escaped_title}]({escaped_link})")
    
    parts.append("")
    parts.append(f"🕐 _Generated: {escape_markdown_v2(datetime.now().strftime('%Y-%m-%d %H:%M UTC'))}_")
    
    # Join all parts
    message = '\n'.join(parts)
    
    # Final length check and truncation if needed
    if len(message) > TELEGRAM_MAX_LENGTH - 200:
        # If too long, reduce number of items
        return format_telegram_message(entries[:2])  # Retry with fewer entries
    
    return message


def test_message_format(message: str) -> bool:
    """Test if message format is valid"""
    # Check for common formatting issues
    issues = []
    
    # Check unescaped characters (but skip those in valid markdown constructs)
    # This is a simplified check - in production you might want more sophisticated validation
    
    # Check balanced markdown
    for marker in ['*', '_', '`']:
        # Count unescaped occurrences
        pattern = f'(?<!\\\\){re.escape(marker)}'
        matches = re.findall(pattern, message)
        if len(matches) % 2 != 0:
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
            # If no recent posts, take the latest one
            recent_posts = [feed.entries[0]]
            logger.info("No recent posts found, using latest post")
        
        logger.info(f"Found {len(recent_posts)} recent post(s)")
        
        # Create a single consolidated message
        message = format_telegram_message(recent_posts)
        
        # Test message format
        if not test_message_format(message):
            logger.warning("Message format issues detected, sending with HTML instead")
            # Convert to HTML as fallback
            html_message = message.replace('\\', '')
            html_message = re.sub(r'\*([^*]+)\*', r'<b>\1</b>', html_message)
            html_message = re.sub(r'_([^_]+)_', r'<i>\1</i>', html_message)
            html_message = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', html_message)
            
            if send_telegram_message(html_message, parse_mode='HTML'):
                logger.info("Message sent successfully with HTML")
            else:
                # Last resort: plain text
                plain_message = re.sub(r'[*_`\[\]()~>#+=|{}.!-]', '', message)
                send_telegram_message(plain_message, parse_mode=None)
        else:
            # Send with MarkdownV2
            if send_telegram_message(message):
                logger.info("Message sent successfully")
            else:
                logger.error("Failed to send message")
                # Try with HTML as fallback
                html_message = message.replace('\\', '')
                html_message = re.sub(r'\*([^*]+)\*', r'<b>\1</b>', html_message)
                html_message = re.sub(r'_([^_]+)_', r'<i>\1</i>', html_message)
                html_message = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', html_message)
                send_telegram_message(html_message, parse_mode='HTML')
        
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
