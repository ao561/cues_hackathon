#  OmniPlan 🤖

A hyper-personalised group chat assistant powered by the deep context of the Model Context Protocol (MCP) to solve chaotic group planning.

---

### 💡 Inspiration

We’ve all been there: trying to plan a simple dinner with friends turns into a chaotic nightmare. Sarah is vegan, Tom has allergies, nobody remembers who can’t do Tuesdays, and someone inevitably suggests a place 2 hours away during rush hour.

We realised the real problem isn't that we can't chat; it's that we are **making decisions blind**. AI should be able to help, but standard chatbots can’t "read minds"—they lack context. They don't know where you are right now, what the weather is like, or that you hate spicy food.

We wanted to solve this by building **OmniPlan**: a tool that combines every user's calendar, location, preferences, and real-time dynamic context in one place.

---

### 🤖 What it Does

OmniPlan is a hyper-personalised group chat assistant that acts as a silent observer. It only chimes in when a user tags `@AI` for help.

When activated, OmniPlan doesn't just "guess" a recommendation. It spins up **5 distinct MCP servers** to gather live context from every user in the chat:

* **📅 Checks Calendars:** Finds the *true* free time for everyone.
* **🗣️ Sentiment Analysis:** Reads the chat history to understand the group's mood and preferences (e.g., "I'm tired of pizza").
* **👤 Profile Matching:** Updates and references individual dietary restrictions and budget constraints.
* **📍 Real-Time Location:** Checks everyone's location to find a central, convenient meeting point.
* **☀️ Live Weather:** Checks if it’s raining to avoid suggesting outdoor seating.

The result is a single, smart suggestion that matches all known criteria, complete with **custom directions for every single person** in the chat.

---

### 🚀 How to Run

This project runs as a single web server application which manages all the underlying MCP servers.

**1. Clone the Repository**

```sh
git clone [https://github.com/ao561/omniplan_cues_hackathon.git](https://github.com/ao561/omniplan_cues_hackathon.git)
cd omniplan_cues_hackathon
```

**2. Create a Virtual Environment (Recommended)**

```sh
# For Mac/Linux
python3 -m venv venv
source venv/bin/activate

# For Windows
python -m venv venv
.\venv\Scripts\activate
```

**3. Install Dependencies**

Install all the required Python packages, including uvicorn.

```sh
pip install -r requirements.txt
```
**4. Set Up Configuration (API Keys)**

The application requires API keys to function. You must create a file named .env in the root of the project directory.

```sh
Create the file:

# For Mac/Linux
touch .env

# For Windows
echo. > .env
```

Now, open the .env file and add the following keys.

```sh
# .env file

# 1. Anthropic API Key (for Claude)
# Get this from the Anthropic Console: [https://console.anthropic.com/](https://console.anthropic.com/)
ANTHROPIC_API_KEY="sk-ant-..."

# 2. Google Maps API Key (for Directions & Location)
# Get this from the Google Cloud Console. You will need to enable:
# - Directions API
# - Geocoding API
# - Maps JavaScript API
GOOGLE_MAPS_API_KEY="AIzaSy..."

# 3. Weather API Key
# Get this from a service like OpenWeatherMap: [https://openweathermap.org/api](https://openweathermap.org/api)
WEATHER_API_KEY="..."
```
Note: Remember to add .env to your .gitignore file if it's not already there. Never commit your secret keys to GitHub.

**5. Run the Web Server**

With your dependencies installed and your .env file in place, run the Uvicorn server. This single command will start the main application, which in turn manages all the MCP servers.

```sh
python -m uvicorn main:app --host 0.0.0.0 --port 9000
```
Why 0.0.0.0?
The IP 10.249.71.64 from your example is a private network IP. By using 0.0.0.0, the server will listen on all available network interfaces, making it accessible to other devices on your local network (e.g., for testing). If you only want to access it on your own machine, you can use 127.0.0.1.

Your OmniPlan assistant is now running and accessible on port 9000.

### ⚙️ How We Built It

We built OmniPlan as a modular agent leveraging the **Model Context Protocol (MCP)** to standardise how the AI accesses and orchestrates information.

* **The Brain:** We used **Claude** (running in `main.py`) as the orchestration engine because of its ability to work effectively with live, hyper-personalised data streams.
* **The Architecture:** The `main:app` server, when run, orchestrates five separate MCP "tools" that provide live context:
    1.  `calendar_server.py`
    2.  `weather_server.py`
    3.  `location_server.py`
    4.  `directions_server.py`
    5.  `sentiment_server.py`
* **Modular Design:** We used a modular MCP design so new context sources (like live event APIs or transit schedules) can be added instantly without re-engineering the core logic.
* **Privacy-First:** The bot is passive and only activates when called. The MCP workflow ensures only our defined tools can run, which helps prevent hallucinations and protects group chat privacy.

---

### 🚧 Challenges We Ran Into

* **The MCP Learning Curve:** Since MCP is a relatively new standard, simply getting the workflow to ensure only our defined tools ran (and nothing else) took significant effort.
* **Context Overload:** Balancing the amount of data fed to the context window was tricky. We had to fine-tune the sentiment analysis to understand both individual and group preferences without overwhelming the model.

---

### 🏆 Accomplishments We're Proud Of

* **True Modularity:** We successfully implemented a modular MCP design where new context sources can be added instantly.
* **Privacy-First Design:** We built a bot that respects group chat privacy by default, only responding when explicitly tagged.
* **Working Prototype:** We delivered a fully working, real-time contextual assistant that successfully uses multiple, simultaneous MCP servers to provide a genuinely useful recommendation.

---

### 🧠 What We Learned

* **The Power of Context:** AI needs more than just a prompt; it needs "deep context" (calendars, location, weather, preferences) to be truly useful and graduate from a toy to a tool.
* **Real-Time Constraints:** Working with live, streaming context required us to optimise how the model handles and prioritises hyper-personalised data from multiple sources at once.

---

### 🚀 What's Next for OmniPlan

We plan to evolve OmniPlan from a meeting scheduler into a fully-fledged travel and social companion.

* **Richer API Integrations:** Integrating Google Maps/Transit, restaurant availability (e.g., OpenTable), live events, and flight status.
* **Proactive Alerts:** Adding proactive alerts for weather shifts, transport delays, or nearby "hidden gem" food matches based on group preferences.
* **True Adaptability:** Making the assistant adapt to where you are and what is happening around you in real-time, becoming a true "co-pilot for your life."
