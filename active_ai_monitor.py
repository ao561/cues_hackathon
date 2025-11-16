"""
Active AI Chat Monitor - Runs alongside the FastAPI server
Watches chat_history.txt for changes and responds when @ai is mentioned
Sends responses directly to WebSocket with timeout handling
"""

import json
import time
import asyncio
from pathlib import Path
from anthropic import Anthropic
from dotenv import load_dotenv
import os
import httpx
from watchfiles import awatch

# Load environment
load_dotenv()

# File paths
CHAT_HISTORY = Path(__file__).parent / "chat_history.txt"
PREPARED_RESPONSE_FILE = Path(__file__).parent / "prepared_response.txt"
LAST_PROCESSED_LINE = Path(__file__).parent / ".last_processed_line"

# Anthropic setup
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-3-5-haiku-20241022")
client = Anthropic(api_key=ANTHROPIC_API_KEY)

# Constants
TRIGGER_WORD = "@ai"
MAX_MESSAGES = 50
RESPONSE_TIMEOUT = 20  # seconds
WEBSOCKET_ENDPOINT = "http://localhost:8000/send_message"


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


def get_recent_context(max_messages=MAX_MESSAGES):
    """
    Get last N messages regardless of when last processed.
    This allows the AI to see consistent context even across multiple calls.
    """
    if not CHAT_HISTORY.exists():
        return []
    
    with open(CHAT_HISTORY, 'r', encoding='utf-8') as f:
        all_lines = f.readlines()
    
    # Always get last max_messages, not just since last trigger
    recent_lines = all_lines[-max_messages:] if len(all_lines) > max_messages else all_lines
    
    messages = []
    for line in recent_lines:
        try:
            msg = json.loads(line.strip())
            messages.append({
                'sender': msg.get('sender', 'Unknown'),
                'message': msg.get('message', '')
            })
        except json.JSONDecodeError:
            continue
    
    return messages


def build_context_prompt(messages):
    """
    Build a context string from messages.
    """
    if not messages:
        return "No chat history available."
    
    context = "Recent conversation:\n"
    for msg in messages:
        context += f"{msg['sender']}: {msg['message']}\n"
    
    return context


async def generate_response(messages):
    """Generate AI response using context"""
    context = build_context_prompt(messages)
    
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


async def send_to_websocket(sender: str, message: str):
    """Send a message to the WebSocket via HTTP endpoint"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                WEBSOCKET_ENDPOINT,
                json={"sender": sender, "message": message},
                timeout=5.0
            )
            return response.status_code == 200
    except Exception as e:
        print(f"Error sending to WebSocket: {e}")
        return False


async def check_for_trigger():
    """Check if the most recent message contains @ai"""
    if not CHAT_HISTORY.exists():
        print("[CHECK] Chat history file doesn't exist")
        return False, 0
    
    last_processed = get_last_processed_line()
    print(f"[CHECK] Last processed line: {last_processed}")
    
    with open(CHAT_HISTORY, 'r', encoding='utf-8') as f:
        all_lines = f.readlines()
    
    current_line_count = len(all_lines)
    print(f"[CHECK] Total lines: {current_line_count}")
    
    # If no new lines since last check, don't trigger
    if current_line_count <= last_processed:
        print(f"[CHECK] No new lines (current: {current_line_count}, last processed: {last_processed})")
        return False, current_line_count
    
    # Only check the last (newest) line for @ai trigger
    last_line = all_lines[-1]
    print(f"[CHECK] Checking last line: {last_line.strip()}")
    
    try:
        msg = json.loads(last_line.strip())
        message = msg.get('message', '')
        
        if TRIGGER_WORD.lower() in message.lower():
            print(f"[CHECK] FOUND TRIGGER in: {message}")
            # Update processed line so we don't trigger on same message again
            set_last_processed_line(current_line_count)
            return True, current_line_count
    except json.JSONDecodeError as e:
        print(f"[CHECK] JSON decode error: {e}")
    
    # Update processed line
    set_last_processed_line(current_line_count)
    print(f"[CHECK] No @ai trigger in last line")
    return False, current_line_count


async def save_response(response_text):
    """Save the AI response for the output system"""
    with open(PREPARED_RESPONSE_FILE, 'w', encoding='utf-8') as f:
        f.write(response_text)
    print(f"[SAVED] Response: {response_text[:100]}...")


async def monitor_loop():
    """Main monitoring loop - watches file for changes"""
    print("=" * 60)
    print("Active AI Chat Monitor Started (File Watcher)")
    print(f"Monitoring: {CHAT_HISTORY}")
    print(f"Trigger: {TRIGGER_WORD}")
    print(f"Response file: {PREPARED_RESPONSE_FILE}")
    print(f"Context: Last {MAX_MESSAGES} messages")
    print(f"Mode: Real-time file watching (instant detection)")
    print("=" * 60)
    print()
    
    # Ensure the chat history file exists
    if not CHAT_HISTORY.exists():
        CHAT_HISTORY.touch()
        print("[INIT] Created chat_history.txt")
    
    async for changes in awatch(CHAT_HISTORY):
        try:
            print(f"[FILE CHANGE DETECTED] {changes}")
            
            # File was modified, check for trigger
            triggered, current_line = await check_for_trigger()
            print(f"[CHECK RESULT] Triggered: {triggered}, Line: {current_line}")
            
            if triggered:
                print(f"\n[TRIGGER DETECTED] @ai mentioned at line {current_line}")
                
                # Get recent context
                recent_messages = get_recent_context()
                print(f"[CONTEXT] Loaded {len(recent_messages)} recent messages")
                
                try:
                    # Generate response with timeout
                    print("[GENERATING] Asking Claude for response...")
                    response = await asyncio.wait_for(
                        generate_response(recent_messages),
                        timeout=RESPONSE_TIMEOUT
                    )
                    
                    if response:
                        print(f"[READY] Response generated: {response[:100]}...")
                        
                        # Send to WebSocket
                        success = await send_to_websocket("AI Assistant", response)
                        if success:
                            print("[SUCCESS] Response sent to WebSocket\n")
                        else:
                            print("[ERROR] Failed to send response to WebSocket\n")
                    else:
                        print("[ERROR] Failed to generate response\n")
                        
                except asyncio.TimeoutError:
                    print(f"[TIMEOUT] Response generation timed out after {RESPONSE_TIMEOUT} seconds")
                    # Send timeout message to WebSocket
                    await send_to_websocket(
                        "AI Assistant", 
                        "Response timeout - still processing, please wait..."
                    )
                    
                except Exception as e:
                    print(f"[ERROR] Exception during response generation: {e}\n")
            
        except KeyboardInterrupt:
            print("\n[STOPPED] AI monitor shut down")
            break
        except Exception as e:
            print(f"[ERROR] {e}")


if __name__ == "__main__":
    asyncio.run(monitor_loop())
