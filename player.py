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
    """Initializes Spotify Client."""
    scope = "user-read-playback-state,user-modify-playback-state"
    auth_manager = SpotifyOAuth(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        redirect_uri=REDIRECT_URI,
        scope=scope,
        open_browser=False,
        cache_path="/home/os/os-project-g03/.spotify_cache_player"
    )
    return spotipy.Spotify(auth_manager=auth_manager, retries=0, requests_timeout=10)

def wake_up_device(sp):
    """Wake up the device by transferring playback."""
    try:
        sp.transfer_playback(device_id=DEVICE_ID, force_play=False)
        time.sleep(0.5)
    except Exception:
        pass

def get_card_action(card_id):
    """Fetch card action from the database."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('SELECT type, uri, name FROM rfid_cards WHERE card_id = ?', (card_id,))
        result = cursor.fetchone()
        conn.close()
        if result:
            return result[0], result[1], result[2]
        return None, None, None
    except Exception as e:
        print(f"Database Error: {e}")
        return None, None, None

def log_playback_history(sp):
    """Logs track name to history (Only for 'Top Tracks' ranking)."""
    try:
        sleep(1)
        current = sp.current_playback()
        if current and current['item']:
            track = current['item']
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            # Only track name is logged here; duration is tracked by the monitor thread
            cursor.execute('''
                INSERT INTO play_logs (track_name, artist_name, duration_ms)
                VALUES (?, ?, ?)
            ''', (track['name'], track['artists'][0]['name'], track['duration_ms']))
            conn.commit()
            conn.close()
            print(f"Logged History: {track['name']}")
    except Exception as e:
        print(f"Logging Error: {e}")

# --- New Function: Real-time Duration Monitor (Background Worker) ---
def monitor_listening_time(sp):
    """Runs in the background to check playback status every 30 seconds."""
    print("--- Time Monitor Started ---")
    while True:
        try:
            # Check playback status
            current = sp.current_playback()

            # If music is currently playing
            if current and current['is_playing']:
                # Record 30 seconds (30000 ms) into the database
                conn = sqlite3.connect(DB_PATH)
                cursor = conn.cursor()
                cursor.execute('INSERT INTO playback_duration (duration_ms) VALUES (?)', (30000,))
                conn.commit()
                conn.close()
                # print("Recorded 30s of listening time...") # Uncomment for debugging

            # Wait for 30 seconds before next check
            time.sleep(30)

        except Exception as e:
            print(f"Monitor Error: {e}")
            time.sleep(30) # Wait before retrying on error

def main():
    reader = SimpleMFRC522()
    sp = setup_spotify()

    if sp is None:
        print("Error: Could not setup Spotify.")
        return

    print(f"--- Player Started. Target: {DEVICE_ID} ---")

    # --- Start Background Thread for Time Monitoring ---
    # Separates time tracking from the main RFID reading loop
    monitor_thread = threading.Thread(target=monitor_listening_time, args=(sp,))
    monitor_thread.daemon = True # Daemon threads exit when the main program exits
    monitor_thread.start()

    try:
        while True:
            # Main RFID Loop
            id, text = reader.read()
            print(f"Card ID Detected: {id}")

            action_type, uri, name = get_card_action(id)

            if action_type:
                print(f"Action: {name}")
                try:
                    wake_up_device(sp)

                    if action_type == "CMD":
                        if uri == "PAUSE":
                            # Toggle Play/Pause Logic
                            current = sp.current_playback()
                            if current and current['is_playing']:
                                sp.pause_playback(device_id=DEVICE_ID)
                                print("Command: Pause")
                            else:
                                sp.start_playback(device_id=DEVICE_ID)
                                print("Command: Resume")

                        elif uri == "NEXT":
                            sp.next_track(device_id=DEVICE_ID)
                            print("Command: Next Track")

                        elif uri == "PREV":
                            # Logic for Previous Track with Context Awareness
                            current = sp.current_playback()
                            # Get progress safely (default to 0 if None)
                            progress = current.get('progress_ms', 0) if current else 0

                            print(f"Current Progress: {progress} ms")

                            # If played for more than 3 seconds (3000 ms)
                            if progress > 3000:
                                sp.previous_track(device_id=DEVICE_ID) # 1st: Restart current song
                                time.sleep(1.0)                        # Wait 1s for Spotify to process
                                sp.previous_track(device_id=DEVICE_ID) # 2nd: Go to previous song
                                print("Double Skip Triggered!")
                            else:
                                # If less than 3 seconds, just skip back once
                                sp.previous_track(device_id=DEVICE_ID)
                                print("Single Skip Triggered!")

                    elif action_type == "TRACK":
                        sp.start_playback(device_id=DEVICE_ID, uris=[uri])
                        log_playback_history(sp) # Log only track name

                    elif action_type == "CONTEXT":
                        sp.start_playback(device_id=DEVICE_ID, context_uri=uri)
                        log_playback_history(sp) # Log only track name

                    # Prevent repetitive scanning
                    sleep(2)

                except spotipy.exceptions.SpotifyException as e:
                    print(f"Spotify Error: {e}")
                    sleep(2)
                except Exception as e:
                    print(f"Error: {e}")
                    sleep(2)
            else:
                print("Unknown Card")
                sleep(2)

    except KeyboardInterrupt:
        print("\nExiting...")

    finally:
        GPIO.cleanup()

if __name__ == "__main__":
    main()