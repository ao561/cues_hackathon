"""
Active AI Chat Monitor - Runs alongside the FastAPI server
Constantly monitors chat_history.txt and responds when @ai is mentioned
Uses Gaussian weighting to prioritize recent messages over older ones
"""

import json
import time
import asyncio
from pathlib import Path
from anthropic import Anthropic
from dotenv import load_dotenv
import os
import math

# Load environment
load_dotenv()

# File paths
CHAT_HISTORY = Path(__file__).parent / "chat_history.txt"
PREPARED_RESPONSE_FILE = Path(__file__).parent / "prepared_response.txt"
LAST_PROCESSED_LINE = Path(__file__).parent / ".last_processed_line"

# Anthropic setup
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-3-5-sonnet-20240620")
client = Anthropic(api_key=ANTHROPIC_API_KEY)

# Constants
TRIGGER_WORD = "@ai"
MAX_MESSAGES = 100
CHECK_INTERVAL = 2  # seconds


def gaussian_weight(position, total, sigma=0.3):
    """
    Calculate Gaussian weight for message importance.
    Recent messages get higher weight, older messages get lower weight.
    
    position: index of message (0 = oldest, total-1 = newest)
    total: total number of messages
    sigma: controls how quickly importance drops off (smaller = more aggressive)
    """
    if total == 1:
        return 1.0
    
    # Normalize position to [-1, 1] where 1 is most recent
    normalized_pos = (2 * position / (total - 1)) - 1
    
    # Gaussian centered at 1 (most recent)
    weight = math.exp(-((normalized_pos - 1) ** 2) / (2 * sigma ** 2))
    
    return weight


def get_last_processed_line():
    """Get the last line number we processed"""
    if LAST_PROCESSED_LINE.exists():
        try:
            return int(LAST_PROCESSED_LINE.read_text().strip())
        except:
            return 0
    return 0


def set_last_processed_line(line_num):
    """Save the last line number we processed"""
    LAST_PROCESSED_LINE.write_text(str(line_num))


def get_weighted_context(max_messages=MAX_MESSAGES):
    """
    Get recent messages with Gaussian importance weighting.
    Returns messages with their weights for context building.
    """
    if not CHAT_HISTORY.exists():
        return []
    
    with open(CHAT_HISTORY, 'r', encoding='utf-8') as f:
        all_lines = f.readlines()
    
    # Get last max_messages
    recent_lines = all_lines[-max_messages:] if len(all_lines) > max_messages else all_lines
    
    messages = []
    for i, line in enumerate(recent_lines):
        try:
            msg = json.loads(line.strip())
            weight = gaussian_weight(i, len(recent_lines))
            messages.append({
                'sender': msg.get('sender', 'Unknown'),
                'message': msg.get('message', ''),
                'weight': weight
            })
        except json.JSONDecodeError:
            continue
    
    return messages


def build_context_prompt(weighted_messages):
    """
    Build a context string emphasizing recent messages based on Gaussian weights.
    """
    if not weighted_messages:
        return "No chat history available."
    
    # Separate into high-weight (recent) and lower-weight (older) messages
    high_weight_threshold = 0.6
    
    recent = []
    older = []
    
    for msg in weighted_messages:
        formatted = f"{msg['sender']}: {msg['message']}"
        if msg['weight'] >= high_weight_threshold:
            recent.append(formatted)
        else:
            older.append(formatted)
    
    context = ""
    
    # Recent messages (emphasized)
    if recent:
        context += "Recent conversation (high importance):\n"
        context += "\n".join(recent)
    
    # Older messages (background context)
    if older:
        if recent:
            context += "\n\n"
        context += "Earlier messages (background context):\n"
        context += "\n".join(older)
    
    return context


async def generate_response(weighted_messages):
    """Generate AI response using weighted context"""
    context = build_context_prompt(weighted_messages)
    
    system_prompt = """You are a helpful AI assistant in a group chat. 

Key behaviors:
- Be conversational and friendly
- Keep responses concise (2-3 sentences max)
- Respond directly to what people are discussing
- If people are talking about food/restaurants, be helpful with suggestions
- Don't be overly formal or verbose

You've been mentioned with @ai, so provide a helpful response based on the conversation."""

    prompt = f"""{context}

Someone mentioned @ai asking for your input. Provide a helpful, conversational response based on the recent discussion."""

    try:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=500,
            system=system_prompt,
            messages=[{
                "role": "user",
                "content": prompt
            }]
        )
        
        return response.content[0].text
    except Exception as e:
        print(f"Error generating response: {e}")
        return None


async def check_for_trigger():
    """Check for @ai mentions in new messages"""
    if not CHAT_HISTORY.exists():
        return False, 0
    
    last_processed = get_last_processed_line()
    
    with open(CHAT_HISTORY, 'r', encoding='utf-8') as f:
        all_lines = f.readlines()
    
    current_line_count = len(all_lines)
    
    # Check new messages
    new_lines = all_lines[last_processed:]
    
    if not new_lines:
        return False, current_line_count
    
    # Check for trigger
    for line in new_lines:
        try:
            msg = json.loads(line.strip())
            message = msg.get('message', '')
            if TRIGGER_WORD.lower() in message.lower():
                return True, current_line_count
        except json.JSONDecodeError:
            continue
    
    # Update processed line even if no trigger
    set_last_processed_line(current_line_count)
    return False, current_line_count


async def save_response(response_text):
    """Save the AI response for the output system"""
    with open(PREPARED_RESPONSE_FILE, 'w', encoding='utf-8') as f:
        f.write(response_text)
    print(f"[SAVED] Response: {response_text[:100]}...")


async def monitor_loop():
    """Main monitoring loop - runs continuously"""
    print("=" * 60)
    print("Active AI Chat Monitor Started")
    print(f"Monitoring: {CHAT_HISTORY}")
    print(f"Trigger: {TRIGGER_WORD}")
    print(f"Response file: {PREPARED_RESPONSE_FILE}")
    print(f"Context: Last {MAX_MESSAGES} messages with Gaussian weighting")
    print(f"Check interval: {CHECK_INTERVAL}s")
    print("=" * 60)
    print()
    
    while True:
        try:
            # Check for trigger
            triggered, current_line = await check_for_trigger()
            
            if triggered:
                print(f"\n[TRIGGER DETECTED] @ai mentioned at line {current_line}")
                
                # Get weighted context
                weighted_messages = get_weighted_context()
                print(f"[CONTEXT] Loaded {len(weighted_messages)} messages with Gaussian weighting")
                
                # Generate response
                print("[GENERATING] Asking Claude for response...")
                response = await generate_response(weighted_messages)
                
                if response:
                    # Save response
                    await save_response(response)
                    print(f"[READY] Response saved and ready to send\n")
                    
                    # Update processed line
                    set_last_processed_line(current_line)
                else:
                    print("[ERROR] Failed to generate response\n")
            
            # Wait before next check
            await asyncio.sleep(CHECK_INTERVAL)
            
        except KeyboardInterrupt:
            print("\n[STOPPED] AI monitor shut down")
            break
        except Exception as e:
            print(f"[ERROR] {e}")
            await asyncio.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    asyncio.run(monitor_loop())
