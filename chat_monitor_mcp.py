# /// script
# dependencies = [
#   "mcp",
#   "anthropic",
#   "python-dotenv",
# ]
# ///

"""
Chat Monitor MCP Server - Provides tools for monitoring and responding to chat
"""

import json
import time
import os
from pathlib import Path
from typing import Any
from mcp.server.fastmcp import FastMCP
from anthropic import Anthropic
from dotenv import load_dotenv

# Load environment
load_dotenv()

# Initialize FastMCP server
mcp = FastMCP("chat-monitor")

# File paths
CHAT_HISTORY = Path(__file__).parent / "chat_history.txt"
PREPARED_RESPONSE_FILE = Path(__file__).parent / "prepared_response.json"
CONVERSATION_SUMMARY_FILE = Path(__file__).parent / ".conversation_summary.json"
LAST_TRIGGER_LINE = Path(__file__).parent / ".last_trigger_line"

# Anthropic setup
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-3-5-sonnet-20240620")
client = Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None


def get_last_trigger_line():
    """Get the line number of the last response trigger"""
    if LAST_TRIGGER_LINE.exists():
        try:
            return int(LAST_TRIGGER_LINE.read_text().strip())
        except:
            return 0
    return 0


def set_last_trigger_line(line_num):
    """Save the line number of the last response trigger"""
    LAST_TRIGGER_LINE.write_text(str(line_num))


def get_conversation_summary():
    """Get the stored conversation summary"""
    if CONVERSATION_SUMMARY_FILE.exists():
        try:
            with open(CONVERSATION_SUMMARY_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return {"summary": "", "last_updated_line": 0}
    return {"summary": "", "last_updated_line": 0}


def save_conversation_summary(summary_text, line_num):
    """Save a summary of the conversation"""
    data = {
        "summary": summary_text,
        "last_updated_line": line_num,
        "timestamp": time.time()
    }
    with open(CONVERSATION_SUMMARY_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)


@mcp.tool()
async def get_recent_messages(max_messages: int = 50) -> str:
    """Get recent chat messages since the last response.
    
    Args:
        max_messages: Maximum number of recent messages to retrieve (default: 50)
    
    Returns:
        Recent chat messages with context summary if available
    """
    if not CHAT_HISTORY.exists():
        return "No chat history found."
    
    last_trigger = get_last_trigger_line()
    
    with open(CHAT_HISTORY, 'r', encoding='utf-8') as f:
        all_lines = f.readlines()
    
    # Get messages since last trigger
    relevant_lines = all_lines[last_trigger:]
    
    # Limit to max_messages
    if len(relevant_lines) > max_messages:
        relevant_lines = relevant_lines[-max_messages:]
    
    messages = []
    for line in relevant_lines:
        try:
            msg = json.loads(line.strip())
            sender = msg.get("sender", "Unknown")
            message = msg.get("message", "")
            messages.append(f"{sender}: {message}")
        except json.JSONDecodeError:
            continue
    
    if not messages:
        return "No new messages since last response."
    
    # Get previous summary
    summary_data = get_conversation_summary()
    previous_summary = summary_data.get("summary", "")
    
    result = f"Recent messages ({len(messages)} total):\n\n"
    result += "\n".join(messages)
    
    if previous_summary:
        result += f"\n\n---\nEarlier conversation context:\n{previous_summary}"
    
    return result


@mcp.tool()
async def prepare_chat_response(response_text: str) -> str:
    """Prepare and save a response to the chat. This stores the response for another system to send.
    
    Args:
        response_text: The response text to save
    
    Returns:
        Confirmation message
    """
    if not CHAT_HISTORY.exists():
        return "Error: No chat history found."
    
    # Get current line number
    with open(CHAT_HISTORY, 'r') as f:
        current_line = len(f.readlines())
    
    # Save the prepared response
    data = {
        "response": response_text,
        "timestamp": time.time(),
        "triggered": True,
        "ready_to_send": True
    }
    
    with open(PREPARED_RESPONSE_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)
    
    # Update trigger line
    set_last_trigger_line(current_line)
    
    return f"Response prepared and saved to {PREPARED_RESPONSE_FILE.name}. Ready for output system to send."


@mcp.tool()
async def create_conversation_summary(summary_text: str) -> str:
    """Create a summary of the conversation so far. This helps maintain context across long conversations.
    
    Args:
        summary_text: A brief summary of the key topics and decisions
    
    Returns:
        Confirmation message
    """
    if not CHAT_HISTORY.exists():
        return "Error: No chat history found."
    
    # Get current line number
    with open(CHAT_HISTORY, 'r') as f:
        current_line = len(f.readlines())
    
    save_conversation_summary(summary_text, current_line)
    
    return f"Conversation summary saved. This will be used as context for future responses."


@mcp.tool()
async def check_for_trigger(trigger_word: str = "@ai") -> str:
    """Check if a trigger word appears in recent unprocessed messages.
    
    Args:
        trigger_word: The word to look for (default: "@ai")
    
    Returns:
        Information about whether trigger was found and how many new messages exist
    """
    if not CHAT_HISTORY.exists():
        return "No chat history found."
    
    last_trigger = get_last_trigger_line()
    
    with open(CHAT_HISTORY, 'r', encoding='utf-8') as f:
        all_lines = f.readlines()
    
    # Get messages since last trigger
    new_lines = all_lines[last_trigger:]
    
    if not new_lines:
        return "No new messages since last check."
    
    # Check for trigger
    triggered = False
    trigger_message = ""
    
    for line in new_lines:
        try:
            msg = json.loads(line.strip())
            message = msg.get("message", "")
            if trigger_word.lower() in message.lower():
                triggered = True
                trigger_message = f"{msg.get('sender', 'Unknown')}: {message}"
                break
        except json.JSONDecodeError:
            continue
    
    if triggered:
        return f"TRIGGER DETECTED!\nMessage: {trigger_message}\nNew messages: {len(new_lines)}\n\nUse get_recent_messages to see all messages and prepare a response."
    else:
        return f"No trigger found. {len(new_lines)} new message(s) waiting."


@mcp.tool()
async def get_prepared_response() -> str:
    """Retrieve the currently prepared response if one exists.
    
    Returns:
        The prepared response or a message if none exists
    """
    if not PREPARED_RESPONSE_FILE.exists():
        return "No prepared response found."
    
    try:
        with open(PREPARED_RESPONSE_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        response = data.get("response", "")
        timestamp = data.get("timestamp", 0)
        ready = data.get("ready_to_send", False)
        
        if not ready:
            return "Response exists but is not marked as ready to send."
        
        return f"Prepared Response:\n{response}\n\nTimestamp: {timestamp}"
    except Exception as e:
        return f"Error reading prepared response: {str(e)}"


if __name__ == "__main__":
    mcp.run()
