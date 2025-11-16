# /// script
# dependencies = [
#   "mcp",
#   "anthropic",
#   "python-dotenv",
# ]
# ///

"""
Sentiment MCP Server - Uses Claude to detect food mentions and sentiment in messages
Saves preferences to user_food_profiles.json
"""

import json
from pathlib import Path
from typing import Any
from mcp.server.fastmcp import FastMCP
from anthropic import Anthropic
from dotenv import load_dotenv
import os

# Load environment
load_dotenv()

# Initialize FastMCP server
mcp = FastMCP("sentiment")

# File paths
USER_PROFILES_FILE = Path(__file__).parent / "user_food_profiles.json"

# Anthropic setup
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-3-5-haiku-20241022")
client = Anthropic(api_key=ANTHROPIC_API_KEY)


def load_user_profiles() -> dict:
    """Load user food profiles from JSON"""
    try:
        with open(USER_PROFILES_FILE, "r") as f:
            return json.load(f)
    except:
        return {}


def save_user_profiles(profiles: dict):
    """Save user food profiles to JSON"""
    with open(USER_PROFILES_FILE, "w") as f:
        json.dump(profiles, f, indent=2)


def update_food_preference(user: str, food: str, category: str):
    """Update a user's food preference in the JSON file"""
    profiles = load_user_profiles()
    
    cats = ["loved", "liked", "neutral", "dislike", "hated"]
    
    if user not in profiles:
        profiles[user] = {c: [] for c in cats}
    
    # Add to new category if not already there
    if food.lower() not in [f.lower() for f in profiles[user][category]]:
        profiles[user][category].append(food)
    
    # Remove from other categories
    for c in cats:
        if c != category:
            profiles[user][c] = [f for f in profiles[user][c] if f.lower() != food.lower()]
    
    save_user_profiles(profiles)


@mcp.tool()
async def analyze_message_sentiment(
    user: str,
    message: str
) -> str:
    """Analyze a message for food mentions and sentiment using Claude.

    Args:
        user: Name of the user who sent the message
        message: The message text to analyze
    
    Returns:
        Analysis result with any detected food preferences
    """
    
    system_prompt = """You are a food sentiment analyzer. Analyze messages to detect:
1. Food items mentioned
2. The user's sentiment toward each food

Sentiment categories:
- loved: Very positive (e.g., "I would kill for", "obsessed with", "love", "amazing")
- liked: Positive (e.g., "like", "good", "enjoy", "pretty good")
- neutral: Neutral mentions (just naming food without opinion)
- dislike: Negative (e.g., "don't like", "not a fan", "meh")
- hated: Very negative (e.g., "hate", "disgusting", "can't stand", "terrible")

Return ONLY a JSON object with this format:
{
  "foods_detected": [
    {"food": "kebab", "sentiment": "loved"},
    {"food": "sushi", "sentiment": "liked"}
  ]
}

If no food is mentioned, return: {"foods_detected": []}

Be smart about detecting food - includes cuisines (italian, chinese), specific dishes (pizza, pasta, burger), ingredients, etc."""

    try:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=300,
            system=system_prompt,
            messages=[{
                "role": "user",
                "content": f"Analyze this message from {user}: \"{message}\""
            }]
        )
        
        result_text = response.content[0].text.strip()
        
        # Parse the JSON response
        try:
            result = json.loads(result_text)
            foods_detected = result.get("foods_detected", [])
            
            if not foods_detected:
                return f"No food mentions detected in message from {user}"
            
            # Update preferences for each detected food
            updates = []
            for item in foods_detected:
                food = item.get("food", "")
                sentiment = item.get("sentiment", "neutral")
                
                if food and sentiment in ["loved", "liked", "neutral", "dislike", "hated"]:
                    update_food_preference(user, food, sentiment)
                    updates.append(f"{user} {sentiment} {food}")
            
            if updates:
                return f"Updated preferences: {', '.join(updates)}"
            else:
                return f"No valid food sentiments detected"
                
        except json.JSONDecodeError:
            return f"Error parsing sentiment analysis: {result_text}"
            
    except Exception as e:
        return f"Error analyzing sentiment: {str(e)}"


@mcp.tool()
async def get_user_preferences(user: str) -> str:
    """Get all food preferences for a specific user.

    Args:
        user: Name of the user
    
    Returns:
        User's food preferences by category
    """
    profiles = load_user_profiles()
    
    if user not in profiles:
        return f"No food preferences found for {user}"
    
    result = [f"Food preferences for {user}:\n"]
    
    for category in ["loved", "liked", "neutral", "dislike", "hated"]:
        foods = profiles[user].get(category, [])
        if foods:
            emoji = {"loved": "❤️", "liked": "👍", "neutral": "😐", "dislike": "👎", "hated": "💔"}[category]
            result.append(f"{emoji} {category.title()}: {', '.join(foods)}")
    
    return "\n".join(result) if len(result) > 1 else f"No food preferences found for {user}"


if __name__ == "__main__":
    mcp.run()
