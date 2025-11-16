"""
Auto Responder - Monitors chat for @ai and generates responses
Run this in the background while your chat server is running
"""

import asyncio
import json
import os
import time
from pathlib import Path
from anthropic import Anthropic
from dotenv import load_dotenv

# Load environment
load_dotenv()

# File paths
CHAT_HISTORY = Path("chat_history.txt")
PREPARED_RESPONSE_FILE = Path("prepared_response.txt")
LAST_TRIGGER_FILE = Path(".last_trigger_line")
USER_PROFILES = Path("user_food_profiles.json")

# Config
TRIGGER_WORD = "@ai"
CHECK_INTERVAL = 1  # Check every 1 second
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
CLAUDE_MODEL = "claude-3-5-sonnet-20241022"

# Initialize Anthropic client
client = Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None


def get_last_trigger_line():
    """Get the line number we last processed"""
    if LAST_TRIGGER_FILE.exists():
        try:
            return int(LAST_TRIGGER_FILE.read_text().strip())
        except:
            return 0
    return 0


def set_last_trigger_line(line_num):
    """Save the line number we just processed"""
    LAST_TRIGGER_FILE.write_text(str(line_num))


def get_user_profiles():
    """Load user food profiles for context"""
    if USER_PROFILES.exists():
        try:
            with open(USER_PROFILES, 'r') as f:
                return json.load(f)
        except:
            return {}
    return {}


async def check_for_trigger():
    """Check if @ai appears in new messages"""
    if not CHAT_HISTORY.exists():
        return None, None
    
    last_trigger = get_last_trigger_line()
    
    with open(CHAT_HISTORY, 'r', encoding='utf-8') as f:
        all_lines = f.readlines()
    
    # Get messages since last check
    new_lines = all_lines[last_trigger:]
    
    if not new_lines:
        return None, None
    
    # Check for @ai trigger
    for i, line in enumerate(new_lines):
        try:
            msg = json.loads(line.strip())
            message = msg.get("message", "")
            sender = msg.get("sender", "Unknown")
            
            if TRIGGER_WORD.lower() in message.lower():
                # Found trigger! Return recent context
                current_line = last_trigger + i + 1
                
                # Get last 20 messages for context
                context_start = max(0, current_line - 20)
                context_lines = all_lines[context_start:current_line + 1]
                
                return current_line, context_lines
        except json.JSONDecodeError:
            continue
    
    # Update last checked line even if no trigger
    set_last_trigger_line(len(all_lines))
    return None, None


async def generate_response(context_lines):
    """Generate AI response using Claude"""
    if not client:
        print("❌ Error: ANTHROPIC_API_KEY not set")
        return "Error: API key not configured"
    
    # Build conversation context
    conversation = []
    for line in context_lines:
        try:
            msg = json.loads(line.strip())
            sender = msg.get("sender", "Unknown")
            message = msg.get("message", "")
            conversation.append(f"{sender}: {message}")
        except:
            continue
    
    # Load user profiles for context
    profiles = get_user_profiles()
    profile_context = ""
    if profiles:
        profile_context = "\n\nUser Food Preferences:\n"
        for user, prefs in profiles.items():
            loved = prefs.get('loved', [])
            disliked = prefs.get('dislike', []) + prefs.get('hated', [])
            if loved or disliked:
                profile_context += f"- {user}: "
                if loved:
                    profile_context += f"Loves {', '.join(loved)}. "
                if disliked:
                    profile_context += f"Dislikes {', '.join(disliked)}."
                profile_context += "\n"
    
    # System prompt
    system_prompt = f"""You are a helpful AI assistant in a group chat helping plan social activities.

Your role:
- Help plan dinners, movies, hangouts
- Be conversational and friendly
- Consider user preferences when making suggestions
- Be concise but helpful

Recent conversation:
{chr(10).join(conversation)}
{profile_context}

Respond naturally to the most recent @ai mention."""
    
    try:
        # Call Claude
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1024,
            messages=[{
                "role": "user",
                "content": "Based on the conversation above, provide a helpful response."
            }],
            system=system_prompt
        )
        
        # Extract text
        response_text = ""
        for block in response.content:
            if hasattr(block, 'text'):
                response_text += block.text
        
        return response_text.strip()
        
    except Exception as e:
        print(f"❌ Error calling Claude: {e}")
        return f"Error generating response: {str(e)}"


async def main():
    """Main monitoring loop"""
    print("🤖 Auto Responder Started")
    print(f"   Monitoring: {CHAT_HISTORY}")
    print(f"   Trigger: {TRIGGER_WORD}")
    print(f"   Checking every {CHECK_INTERVAL} seconds")
    print("   Press Ctrl+C to stop\n")
    
    if not client:
        print("❌ WARNING: ANTHROPIC_API_KEY not set in .env file!")
        print("   Auto responder will not work without it.\n")
    
    try:
        while True:
            # Check for trigger
            trigger_line, context = await check_for_trigger()
            
            if trigger_line and context:
                print(f"\n🎯 Trigger detected at line {trigger_line}")
                print("   Generating response...")
                
                # Generate response
                response = await generate_response(context)
                
                # Save to file
                with open(PREPARED_RESPONSE_FILE, 'w', encoding='utf-8') as f:
                    f.write(response)
                
                print(f"   ✅ Response saved to {PREPARED_RESPONSE_FILE.name}")
                print(f"   Preview: {response[:100]}...\n")
                
                # Update last processed line
                set_last_trigger_line(trigger_line)
            
            # Wait before next check
            await asyncio.sleep(CHECK_INTERVAL)
            
    except KeyboardInterrupt:
        print("\n\n👋 Auto Responder Stopped")


if __name__ == "__main__":
    asyncio.run(main())
