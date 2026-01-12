import spotipy
from spotipy.oauth2 import SpotifyOAuth

CLIENT_ID = "Client_ID_Here"
CLIENT_SECRET = "Client_Secret_Here"

sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET,
    redirect_uri="http://127.0.0.1:8000/callback",
    scope="user-read-playback-state",
    open_browser=False
))

print("\n=== Find Devices Opening Spotify ===")
try:
    devices = sp.devices()
    for d in devices['devices']:
        print(f"Find Device!: {d['name']}")
        print(f"Device ID: {d['id']}")
        print("-" * 30)

    if len(devices['devices']) == 0:
        print("can't find any devices! (Don't forget to leave the music playing on your computer/phone.")
except Exception as e:
    print(f"Error: {e}")
