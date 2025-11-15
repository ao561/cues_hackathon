# Multi-User Calendar Integration - How It Works

## Overview
Your chat app now supports Google Calendar integration for all users! Each user can connect their own calendar independently.

---

## How Users Connect Their Calendar

### Step 1: Join the Chat
- User enters their name and joins the chat (as before)

### Step 2: Click "Connect Calendar" Button
- A green "📅 Connect Calendar" button appears in the sidebar
- User clicks this button

### Step 3: Authenticate with Google
- A popup window opens with Google OAuth login
- User signs in with their Google account
- User grants calendar access permissions
- Popup closes automatically after successful authentication

### Step 4: Calendar Connected!
- Button changes to "✅ Calendar Connected"
- Status message shows "Calendar access enabled"
- User can now use calendar features in the chat

---

## Technical Implementation

### For Each User:
1. **Unique Auth URL**: `/auth/google-login/{username}`
   - Each user gets their own authentication link
   - Username is tracked through the OAuth state parameter

2. **Credential Storage**: 
   ```python
   user_credentials[username] = credentials
   ```
   - Each user's calendar credentials are stored separately
   - Accessible only to that specific user

3. **Check Auth Status**: `/auth/status/{username}`
   - Check if a specific user has connected their calendar
   - Returns authentication status per user

---

## User Experience Flow

```
User: "Alice" joins chat
    ↓
Alice clicks "Connect Calendar"
    ↓
Popup opens → Google OAuth
    ↓
Alice signs in with her Google account
    ↓
Alice grants calendar permissions
    ↓
Credentials stored as: user_credentials["Alice"]
    ↓
Button shows: "✅ Calendar Connected"
    ↓
Alice can now use calendar features!
```

---

## API Endpoints

### Authentication
- `GET /auth/google-login/{username}` - Start OAuth for specific user
- `GET /auth/callback` - Handle OAuth callback (auto-detects user)
- `GET /auth/status/{username}` - Check if user is authenticated

### Calendar Operations (Coming Soon)
- `GET /calendar/events/{username}` - Get user's calendar events
- `POST /calendar/create-event/{username}` - Create event for user
- `GET /calendar/free-busy/{username}` - Check user's availability

---

## Privacy & Security

### ✅ What's Secure:
- Each user authenticates with their own Google account
- Credentials are stored separately per user
- Users can only access their own calendar data
- OAuth tokens are not shared between users

### ⚠️ Current Limitations (For Production):
- Credentials stored in memory (lost on server restart)
- No database persistence yet
- Need to add token refresh logic
- Should add user session management

---

## Next Steps for Production

### 1. Add Database Storage
```python
# Instead of in-memory dictionary
user_credentials = {}

# Use database
class UserCalendar(Base):
    username = Column(String, primary_key=True)
    access_token = Column(String)
    refresh_token = Column(String)
    expires_at = Column(DateTime)
```

### 2. Add Token Refresh
- Google tokens expire after 1 hour
- Use refresh_token to get new access_token
- Automatic token renewal

### 3. Add Calendar Commands to Chat
Example messages that could trigger calendar actions:
- "Schedule a meeting tomorrow at 3pm"
- "What's on my calendar today?"
- "When is everyone free this week?"
- "Book lunch with John on Friday"

### 4. Multi-User Scheduling
- Find times when multiple users are free
- Check availability across all participants
- Suggest best meeting times

---

## Testing Multiple Users

### Test Scenario:
1. **User 1 (Alice)**:
   - Join chat as "Alice"
   - Connect calendar
   - Creates events

2. **User 2 (Bob)**:
   - Join chat as "Bob" (different browser/incognito)
   - Connect his own calendar
   - His credentials are separate from Alice's

3. **Group Scheduling**:
   - Alice asks: "When can we meet this week?"
   - System checks both Alice's and Bob's calendars
   - Suggests times when both are free

---

## Adding More Users

The system automatically supports unlimited users:
- Each user has unique credentials
- No configuration needed
- Just click "Connect Calendar" and authenticate

---

## For Developers

### Add Calendar Features to Chat:

```python
@app.websocket("/ws/{client_name}")
async def websocket_endpoint(websocket: WebSocket, client_name: str):
    # ... existing code ...
    
    # Check if message is a calendar command
    if "schedule" in data.lower() or "meeting" in data.lower():
        if client_name in user_credentials:
            # User has calendar connected
            # Process calendar command
            await handle_calendar_command(client_name, data)
        else:
            # Prompt to connect calendar
            await websocket.send_text(
                json.dumps({
                    "sender": "System",
                    "message": "Please connect your calendar first!"
                })
            )
```

---

## Summary

✅ **Multi-user support**: Each user connects their own calendar
✅ **Easy setup**: One-click OAuth authentication
✅ **Secure**: Separate credentials per user
✅ **Scalable**: Supports unlimited users
✅ **Ready to extend**: Easy to add calendar commands

**All users just need to click "Connect Calendar" and sign in with their Google account!**
