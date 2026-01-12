#!/usr/bin/env python
from mfrc522 import SimpleMFRC522
import RPi.GPIO as GPIO
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from time import sleep
import time
import sqlite3

# --- Configuration ---
DEVICE_ID = "Raspi_Speaker_ID_Here" # Raspi-Speaker ID
DB_PATH = "/home/os/os-project-g03/database.db"

# --- Credentials ---
CLIENT_ID = "Client_ID_Here"
CLIENT_SECRET = "Client_Secret_Here"
REDIRECT_URI = "REDIRECT_URI_Here"

def setup_spotify():
    """Initializes Spotify Client with retry protection."""
    scope = "user-read-playback-state,user-modify-playback-state"
    auth_manager = SpotifyOAuth(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        redirect_uri=REDIRECT_URI,
        scope=scope,
        open_browser=False,
        cache_path="/home/os/os-project-g03/.spotify_cache_player"
    )
    # retries=0 prevents spamming API when errors occur
    return spotipy.Spotify(auth_manager=auth_manager, retries=0, requests_timeout=10)

def wake_up_device(sp):
    """Transfers playback to device to wake it up."""
    try:
        sp.transfer_playback(device_id=DEVICE_ID, force_play=False)
        time.sleep(0.5)
    except Exception:
        pass

def get_card_action(card_id):
    """Queries the database for card actions."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('SELECT type, uri, name FROM rfid_cards WHERE card_id = ?', (card_id,))
        result = cursor.fetchone()
        conn.close()
        if result:
            return result[0], result[1], result[2] # type, uri, name
        return None, None, None
    except Exception as e:
        print(f"Database Error: {e}")
        return None, None, None

def log_playback(sp):
    """Logs the current track to the database for stats."""
    try:
        sleep(1) # Wait for Spotify to update status
        current = sp.current_playback()
        if current and current['item']:
            track = current['item']
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO play_logs (track_name, artist_name, duration_ms)
                VALUES (?, ?, ?)
            ''', (track['name'], track['artists'][0]['name'], track['duration_ms']))
            conn.commit()
            conn.close()
            print(f"Logged: {track['name']}")
    except Exception as e:
        print(f"Logging Error: {e}")

def main():
    reader = SimpleMFRC522()
    sp = setup_spotify()

    if sp is None:
        print("Error: Could not setup Spotify.")
        return

    print(f"--- Player Started. Target: {DEVICE_ID} ---")

    try:
        while True:
            # 1. Read Card
            id, text = reader.read()
            print(f"Card ID Detected: {id}")

            # 2. Get Action from Database
            action_type, uri, name = get_card_action(id)

            if action_type:
                print(f"Action: {name}")

                try:
                    # Wake up speaker
                    wake_up_device(sp)

                    if action_type == "CMD":
                        if uri == "PAUSE": sp.pause_playback(device_id=DEVICE_ID)
                        elif uri == "NEXT": sp.next_track(device_id=DEVICE_ID)
                        elif uri == "PREV": sp.previous_track(device_id=DEVICE_ID)

                    elif action_type == "TRACK":
                        sp.start_playback(device_id=DEVICE_ID, uris=[uri])
                        log_playback(sp) # Save log

                    elif action_type == "CONTEXT":
                        sp.start_playback(device_id=DEVICE_ID, context_uri=uri)
                        log_playback(sp) # Save log

                    # Prevent double scanning
                    sleep(2)

                except spotipy.exceptions.SpotifyException as e:
                    print(f"Spotify Error: {e}")
                    if e.http_status == 429:
                        retry_after = int(e.headers.get('Retry-After', 5))
                        print(f"Rate Limit! Sleeping {retry_after}s...")
                        sleep(retry_after)
                    else:
                        sleep(2)
                except Exception as e:
                    print(f"Error: {e}")
                    sleep(2)
            else:
                print("Unknown Card (Not in Database)")
                sleep(2)

    except KeyboardInterrupt:
        print("\nExiting...")

    finally:
        GPIO.cleanup()

if __name__ == "__main__":
    main()