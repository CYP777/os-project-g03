from flask import Flask, jsonify, render_template, request
import spotipy
from spotipy.oauth2 import SpotifyOAuth
import sqlite3
from datetime import datetime
import os

app = Flask(__name__)

# --- Configuration ---
# Use absolute path to avoid errors when running with systemd
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "database.db")
CACHE_PATH = os.path.join(BASE_DIR, ".spotify_cache_display")

# Spotify API Credentials
CLIENT_ID = "26a85c51d62d402bad50dd5a12c6417e"
CLIENT_SECRET = "2697b8caca0845488ce84a714f705d52"
REDIRECT_URI = "http://127.0.0.1:8000/callback"

# --- Spotify Setup ---
sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET,
    redirect_uri=REDIRECT_URI,
    scope="user-read-playback-state,user-read-currently-playing,user-read-recently-played",
    open_browser=False,
    cache_path=CACHE_PATH
))

def init_db():
    """Initializes the SQLite database with a new table for real-time tracking."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Table 1: RFID Logs (Raw scan logs)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS rfid_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Table 2: Playback History (Stores track names for "Top Tracks" stats)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS play_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            track_name TEXT,
            artist_name TEXT,
            duration_ms INTEGER,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # --- New Table: Real Listening Duration (Stores actual listening time) ---
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS playback_duration (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            duration_ms INTEGER,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Table 3: Card Mapping
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS rfid_cards (
            card_id INTEGER PRIMARY KEY,
            type TEXT,
            uri TEXT,
            name TEXT
        )
    ''')

    conn.commit()
    conn.close()
    seed_data()

def seed_data():
    """Seeds initial data if the card table is empty."""
    # Hardcoded map from previous version
    OLD_MAP = {
        71526473880:  ("CMD", "PAUSE", "Pause Command"),
        427988768397: ("CMD", "PREV", "Previous Track"),
        427358901798: ("CMD", "NEXT", "Next Track"),
        429402117779: ("TRACK", "spotify:track:5QxNmQBXpLPemzpDvsuiLM", "Track: 5QxNm..."),
        76284449903:  ("CONTEXT", "spotify:playlist:46IEY4GPFsVMSJv9uemtBu", "Playlist: 46IEY..."),
        69098037494:  ("TRACK", "spotify:track:0WbMK4wrZ1wFSty9F7FCgu", "Track: 0WbMK..."),
        69136638133:  ("CONTEXT", "spotify:playlist:3jc1CXzkmIOY8oct0GdaZo", "Playlist: 3jc1C..."),
        426779563616: ("TRACK", "spotify:track:0tIkUSA5njpsBaTAx3z25z", "Track: 0tIkU..."),
        426625619647: ("CONTEXT", "spotify:playlist:5V5qK0cHXCDwkZC8Cikxv4", "Playlist: 5V5qK..."),
        428280338173: ("CONTEXT", "spotify:playlist:3zACSOuS7cj5TOROIHrAVc", "Playlist: 3zACS..."),
        427966223959: ("CONTEXT", "spotify:playlist:18BmB9NtcZua885Q8hQvcb", "Playlist: 18BmB...")
    }
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT count(*) FROM rfid_cards')
    if cursor.fetchone()[0] == 0:
        for card_id, val in OLD_MAP.items():
            cursor.execute('INSERT OR IGNORE INTO rfid_cards (card_id, type, uri, name) VALUES (?, ?, ?, ?)',
                           (card_id, val[0], val[1], val[2]))
        conn.commit()
    conn.close()

init_db()

# --- Routes ---

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/current-song')
def get_current_song():
    try:
        current_track = sp.current_playback()
        if current_track and current_track['is_playing']:
            item = current_track['item']
            progress = (current_track['progress_ms'] / item['duration_ms']) * 100
            return jsonify({
                'playing': True,
                'title': item['name'],
                'artist': item['artists'][0]['name'] if item['artists'] else "Unknown",
                'cover': item['album']['images'][0]['url'] if item['album']['images'] else "",
                'progress': progress
            })
        return jsonify({'playing': False})
    except Exception as e:
        return jsonify({'playing': False, 'error': str(e)})

@app.route('/stats')
def get_stats():
    """API: Returns playback statistics."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        # 1. Calculate Listening Time (Real Time)
        # Fetch data from the new 'playback_duration' table
        today = datetime.now().strftime('%Y-%m-%d')
        cursor.execute("SELECT SUM(duration_ms) FROM playback_duration WHERE date(timestamp) = ?", (today,))
        total_ms = cursor.fetchone()[0] or 0
        total_minutes = round(total_ms / 60000)

        # 2. Get Top Tracks (Still uses 'play_logs' as before)
        cursor.execute('''
            SELECT track_name, artist_name, COUNT(*) as count
            FROM play_logs
            GROUP BY track_name
            ORDER BY count DESC LIMIT 5
        ''')
        top_tracks = cursor.fetchall()

        conn.close()
        return jsonify({'today_minutes': total_minutes, 'top_tracks': top_tracks})
    except Exception as e:
        return jsonify({'error': str(e)})

@app.route('/api/cards', methods=['GET', 'POST'])
def manage_cards():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    if request.method == 'POST':
        data = request.json
        cursor.execute('INSERT OR REPLACE INTO rfid_cards (card_id, type, uri, name) VALUES (?, ?, ?, ?)',
                       (data['id'], data['type'], data['uri'], data['name']))
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    cursor.execute('SELECT * FROM rfid_cards')
    cards = [{'id': r[0], 'type': r[1], 'uri': r[2], 'name': r[3]} for r in cursor.fetchall()]
    conn.close()
    return jsonify(cards)

@app.route('/api/cards/<int:card_id>', methods=['DELETE'])
def delete_card(card_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM rfid_cards WHERE card_id = ?', (card_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)