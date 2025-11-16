"""
Active AI Chat Monitor - Runs alongside the FastAPI server
Watches chat_history.txt for changes and responds when @ai is mentioned
Sends responses directly to WebSocket with timeout handling
Now with MCP tool integration!
"""

import json
import time
import asyncio
import datetime
from pathlib import Path
from anthropic import Anthropic
from dotenv import load_dotenv
import os
import httpx
from watchfiles import awatch

# Import MCP tool functions
import sys
sys.path.append(str(Path(__file__).parent))

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
RESPONSE_TIMEOUT = 60  # seconds (increased for tool use)
WEBSOCKET_ENDPOINT = "http://localhost:8000/send_message"

# Tool definitions for Anthropic API
TOOLS = [
    {
        "name": "check_availability",
        "description": "Check calendar availability for a list of people. Shows if they are free or busy in the next few hours.",
        "input_schema": {
            "type": "object",
            "properties": {
                "people": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of person names (e.g., ['Simon', 'Mahdi', 'Amaan'])"
                },
                "hours_ahead": {
                    "type": "integer",
                    "description": "Number of hours to check ahead (default: 2)",
                    "default": 2
                }
            },
            "required": ["people"]
        }
    },
    {
        "name": "get_current_locations",
        "description": "Get the current or upcoming location for each person based on their calendar events. Shows where people will be.",
        "input_schema": {
            "type": "object",
            "properties": {
                "people": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of person names"
                },
                "hours_ahead": {
                    "type": "integer",
                    "description": "Number of hours to check ahead (default: 2)",
                    "default": 2
                }
            },
            "required": ["people"]
        }
    },
    {
        "name": "find_common_free_time",
        "description": "Find common free time slots when all specified people are available for a meetup.",
        "input_schema": {
            "type": "object",
            "properties": {
                "people": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of person names"
                },
                "hours_ahead": {
                    "type": "integer",
                    "description": "Number of hours to search (default: 8)",
                    "default": 8
                }
            },
            "required": ["people"]
        }
    },
    {
        "name": "find_restaurants",
        "description": "Find restaurants near a specific location using coordinates.",
        "input_schema": {
            "type": "object",
            "properties": {
                "latitude": {
                    "type": "number",
                    "description": "Latitude of the location"
                },
                "longitude": {
                    "type": "number",
                    "description": "Longitude of the location"
                },
                "radius": {
                    "type": "integer",
                    "description": "Search radius in meters (default: 1500)",
                    "default": 1500
                },
                "cuisine_type": {
                    "type": "string",
                    "description": "Optional cuisine filter (e.g., 'italian', 'chinese')"
                }
            },
            "required": ["latitude", "longitude"]
        }
    },
    {
        "name": "find_restaurants_by_address",
        "description": "Find restaurants near an address. Combines geocoding and restaurant search.",
        "input_schema": {
            "type": "object",
            "properties": {
                "address": {
                    "type": "string",
                    "description": "Address to search near (e.g., 'Trumpington Street, Cambridge')"
                },
                "radius": {
                    "type": "integer",
                    "description": "Search radius in meters (default: 1500)",
                    "default": 1500
                },
                "cuisine_type": {
                    "type": "string",
                    "description": "Optional cuisine filter"
                }
            },
            "required": ["address"]
        }
    },
    {
        "name": "analyze_food_preferences",
        "description": "Analyze food preferences mentioned in the chat history to suggest restaurants based on what people like/dislike.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "geocode_address",
        "description": "Convert an address to latitude/longitude coordinates. Useful for finding locations before searching for restaurants.",
        "input_schema": {
            "type": "object",
            "properties": {
                "address": {
                    "type": "string",
                    "description": "Address to geocode (e.g., 'Trumpington Street, Cambridge')"
                }
            },
            "required": ["address"]
        }
    },
    {
        "name": "analyze_message_sentiment",
        "description": "Analyze a user's message for food mentions and sentiment. Automatically updates their food preferences. Use this when you notice people talking about food.",
        "input_schema": {
            "type": "object",
            "properties": {
                "user": {
                    "type": "string",
                    "description": "Name of the user who sent the message"
                },
                "message": {
                    "type": "string",
                    "description": "The message text to analyze"
                }
            },
            "required": ["user", "message"]
        }
    },
    {
        "name": "get_user_food_preferences",
        "description": "Get all saved food preferences for a specific user. Shows what they love, like, are neutral about, dislike, and hate.",
        "input_schema": {
            "type": "object",
            "properties": {
                "user": {
                    "type": "string",
                    "description": "Name of the user"
                }
            },
            "required": ["user"]
        }
    },
    {
        "name": "get_group_directions",
        "description": "Get detailed directions for all group members to a destination. Shows step-by-step directions for each person.",
        "input_schema": {
            "type": "object",
            "properties": {
                "restaurant_name_or_address": {
                    "type": "string",
                    "description": "Restaurant name or address to get directions to"
                },
                "travel_mode": {
                    "type": "string",
                    "description": "Travel mode: 'driving', 'walking', 'bicycling', or 'transit' (default: 'walking')",
                    "enum": ["driving", "walking", "bicycling", "transit"],
                    "default": "walking"
                }
            },
            "required": ["restaurant_name_or_address"]
        }
    },
    {
        "name": "get_travel_time_summary",
        "description": "Get a quick summary of travel times for all group members to a destination. Useful for comparing who's closest.",
        "input_schema": {
            "type": "object",
            "properties": {
                "restaurant_name_or_address": {
                    "type": "string",
                    "description": "Restaurant name or address"
                }
            },
            "required": ["restaurant_name_or_address"]
        }
    },
    {
        "name": "list_group_members",
        "description": "List all group members and their current addresses/locations.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    }
]


# Tool execution functions - these call the actual MCP implementations
async def execute_tool(tool_name: str, tool_input: dict):
    """Execute a tool and return the result"""
    try:
        if tool_name == "check_availability":
            from calendar_server import check_availability
            result = await check_availability(
                people=tool_input["people"],
                hours_ahead=tool_input.get("hours_ahead", 2)
            )
            return result
        
        elif tool_name == "get_current_locations":
            from calendar_server import get_current_locations
            result = await get_current_locations(
                people=tool_input["people"],
                hours_ahead=tool_input.get("hours_ahead", 2)
            )
            return result
        
        elif tool_name == "find_common_free_time":
            from calendar_server import find_common_free_time
            result = await find_common_free_time(
                people=tool_input["people"],
                hours_ahead=tool_input.get("hours_ahead", 8)
            )
            return result
        
        elif tool_name == "find_restaurants":
            from location_server import find_restaurants
            result = await find_restaurants(
                latitude=tool_input["latitude"],
                longitude=tool_input["longitude"],
                radius=tool_input.get("radius", 1500),
                cuisine_type=tool_input.get("cuisine_type")
            )
            return result
        
        elif tool_name == "find_restaurants_by_address":
            from location_server import find_restaurants_by_address
            result = await find_restaurants_by_address(
                address=tool_input["address"],
                radius=tool_input.get("radius", 1500),
                cuisine_type=tool_input.get("cuisine_type")
            )
            return result
        
        elif tool_name == "analyze_food_preferences":
            from location_server import analyze_food_preferences
            result = await analyze_food_preferences()
            return result
        
        elif tool_name == "geocode_address":
            from location_server import geocode_address
            result = await geocode_address(
                address=tool_input["address"]
            )
            return result
        
        elif tool_name == "analyze_message_sentiment":
            from sentiment_server import analyze_message_sentiment
            result = await analyze_message_sentiment(
                user=tool_input["user"],
                message=tool_input["message"]
            )
            return result
        
        elif tool_name == "get_user_food_preferences":
            from sentiment_server import get_user_preferences
            result = await get_user_preferences(
                user=tool_input["user"]
            )
            return result
        
        elif tool_name == "get_group_directions":
            from directions_server import get_group_directions
            result = await get_group_directions(
                restaurant_name_or_address=tool_input["restaurant_name_or_address"],
                travel_mode=tool_input.get("travel_mode", "walking")
            )
            return result
        
        elif tool_name == "get_travel_time_summary":
            from directions_server import get_travel_time_summary
            result = await get_travel_time_summary(
                restaurant_name_or_address=tool_input["restaurant_name_or_address"]
            )
            return result
        
        elif tool_name == "list_group_members":
            from directions_server import list_group_members
            result = await list_group_members()
            return result
        
        else:
            return f"Unknown tool: {tool_name}"
    
    except Exception as e:
        return f"Error executing {tool_name}: {str(e)}"


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
    """Generate AI response using context and tools"""
    context = build_context_prompt(messages)
    
    system_prompt = """You are a helpful AI assistant in a group chat with access to powerful tools.

Key behaviors:
- Be conversational and friendly
- Keep responses SHORT and concise (3-5 sentences max)
- Each bullet point MUST be on its own line with a line break before and after
- Format all responses with proper spacing between sections

When people ask for restaurant recommendations:
  • Use analyze_food_preferences to understand what everyone likes
  
  • Pick ONE single restaurant that works for the whole group
  
  • ALWAYS use get_group_directions after picking a restaurant
  
  • Consider everyone's location when choosing

Use tools proactively:
  • Check calendars when people discuss meeting times
  
  • Get directions whenever you recommend a specific place
  
  • Check locations to help coordinate

Give clear, actionable recommendations and always call get_group_directions when suggesting a place.

Available people: Amaan, Simon, Hayyan, Mahdi, Ardil

You've been mentioned with @ai, so provide helpful responses and use tools to give accurate, contextual information."""

    prompt = f"""{context}

Someone mentioned @ai asking for your input. Provide a helpful response based on the conversation. Use tools if needed to give accurate information."""

    try:
        # Initial API call with tools
        conversation_messages = [{
            "role": "user",
            "content": prompt
        }]
        
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1000,
            system=system_prompt,
            tools=TOOLS,
            messages=conversation_messages
        )
        
        # Tool use loop
        while response.stop_reason == "tool_use":
            # Extract tool uses from response
            tool_uses = [block for block in response.content if block.type == "tool_use"]
            
            # Create a single thinking message showing all tools being used
            tool_descriptions = {
                "check_availability": "Checking calendar availability",
                "get_current_locations": "Getting current locations", 
                "find_common_free_time": "Finding common free time",
                "find_restaurants": "Finding restaurants",
                "find_restaurants_by_address": "Searching for restaurants nearby",
                "analyze_food_preferences": "Analyzing food preferences",
                "geocode_address": "Looking up address",
                "analyze_message_sentiment": "Understanding food preferences",
                "get_user_food_preferences": "Retrieving saved preferences",
                "get_group_directions": "Getting directions for everyone",
                "get_travel_time_summary": "Calculating travel times",
                "list_group_members": "Checking group members"
            }
            
            # Build status message
            if len(tool_uses) == 1:
                status = tool_descriptions.get(tool_uses[0].name, "Processing")
                thinking_msg = f"🤔 {status}..."
            else:
                status_items = [tool_descriptions.get(t.name, "Processing") for t in tool_uses]
                thinking_msg = f"🤔 Working on this...\n• " + "\n• ".join(status_items)
            
            await send_to_websocket("AI Assistant", thinking_msg)
            
            for tool_use in tool_uses:
                print(f"[TOOL USE] {tool_use.name} with input: {tool_use.input}")
            
            # Execute tools and build tool results
            tool_results = []
            for tool_use in tool_uses:
                result = await execute_tool(tool_use.name, tool_use.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": str(result)
                })
            
            # Add assistant's response and tool results to conversation
            conversation_messages.append({
                "role": "assistant",
                "content": response.content
            })
            conversation_messages.append({
                "role": "user",
                "content": tool_results
            })
            
            # Continue conversation with tool results
            response = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=1000,
                system=system_prompt,
                tools=TOOLS,
                messages=conversation_messages
            )
        
        # Extract final text response
        text_blocks = [block.text for block in response.content if hasattr(block, "text")]
        return " ".join(text_blocks) if text_blocks else "I processed your request but couldn't generate a response."
        
    except Exception as e:
        print(f"Error generating response: {e}")
        import traceback
        traceback.print_exc()
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
    
    with open(CHAT_HISTORY, 'r', encoding='utf-8') as f:
        all_lines = f.readlines()
    
    current_line_count = len(all_lines)
    print(f"[CHECK] Total lines: {current_line_count}")
    
    # If no lines, don't trigger
    if current_line_count == 0:
        print(f"[CHECK] No lines in chat history")
        return False, current_line_count
    
    # Only check the last (newest) line for @ai trigger
    last_line = all_lines[-1]
    print(f"[CHECK] Checking last line: {last_line.strip()}")
    
    last_processed = get_last_processed_line()
    
    try:
        msg = json.loads(last_line.strip())
        message = msg.get('message', '')
        sender = msg.get('sender', '')
        
        # Don't respond to AI's own messages
        if sender == "AI Assistant":
            print(f"[CHECK] Skipping AI Assistant's own message")
            return False, current_line_count
        
        if TRIGGER_WORD.lower() in message.lower():
            # Only trigger if we haven't processed this line number before
            if current_line_count > last_processed:
                print(f"[CHECK] FOUND TRIGGER in: {message}")
                # Update processed line so we don't trigger on same message again
                set_last_processed_line(current_line_count)
                return True, current_line_count
            else:
                print(f"[CHECK] Already processed line {current_line_count}")
                return False, current_line_count
    except json.JSONDecodeError as e:
        print(f"[CHECK] JSON decode error: {e}")
    
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
    
    try:
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
                print(f"[ERROR] Processing change: {e}")
                
    except KeyboardInterrupt:
        print("\n[STOPPED] AI monitor shut down")
    except Exception as e:
        print(f"[ERROR] File watcher error: {e}")
        print("[RESTART] Restarting file watcher in 2 seconds...")
        await asyncio.sleep(2)
        # Recursively restart the monitor
        await monitor_loop()


if __name__ == "__main__":
    asyncio.run(monitor_loop())
