# filename: media_check.py
import asyncio
import sys

# This script checks if the winrt libraries can access the system's media information.
# It is completely independent of the PCLink application.

async def check_media_session():
    """Tries to get the current media session and print its details."""
    print("--- Starting Media Diagnosis ---")

    if sys.platform != "win32":
        print("This script only works on Windows.")
        return

    try:
        from winsdk.windows.media.control import \
            GlobalSystemMediaTransportControlsSessionManager as MediaManager
        
        print("Successfully imported winrt media libraries.")
    except ImportError as e:
        print(f"FATAL ERROR: Could not import the necessary libraries. Please reinstall them.")
        print(f"Details: {e}")
        return

    try:
        print("Attempting to get the media manager...")
        manager = await MediaManager.request_async()
        
        if not manager:
            print("ERROR: Failed to get the MediaManager from Windows. The service might be disabled.")
            return

        print("Media manager found. Attempting to get the current session...")
        session = manager.get_current_session()

        if session:
            print("\nSUCCESS: An active media session was found!")
            properties = await session.try_get_media_properties_async()
            print(f"  - Title:  {properties.title}")
            print(f"  - Artist: {properties.artist}")
            print(f"  - Album:  {properties.album_title}")
        else:
            print("\nRESULT: No active media session was found by the system.")
            print("This means no compatible application (Spotify, new Media Player, browser media) was detected.")

    except Exception as e:
        print(f"\n--- An unexpected error occurred ---")
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()

    print("\n--- Diagnosis Complete ---")


if __name__ == "__main__":
    try:
        asyncio.run(check_media_session())
    except Exception as e:
        print(f"A top-level error occurred: {e}")