# ================================================================
#  pi_sender.py  —  Runs on your Raspberry Pi
#
#  This script connects to your laptop over Bluetooth and sends
#  a photo.  It can handle large files (15 MB and above).
#
#  BEFORE YOU RUN THIS:
#    1. Edit config.py — set LAPTOP_MAC and IMAGE_PATH
#    2. Install the Bluetooth library (run once):
#         sudo apt-get install bluetooth bluez python3-bluez
#         pip3 install PyBluez
#    3. Start laptop_receiver.py on your laptop FIRST
#    4. Then run this on the Pi:
#         python3 pi_sender.py
# ================================================================


# --- What these imports do ------------------------------------
#
#  'os'       — lets us check if a file exists and get its size
#  'struct'   — turns a number into raw bytes (for the size header)
#  'time'     — lets us measure how long the transfer takes
#  'config'   — our own settings file (config.py in this folder)
#
import os
import struct
import time

from bluetooth.config import (
    LAPTOP_MAC,
    BLUETOOTH_PORT,
    IMAGE_PATH,
    CHUNK_SIZE,
    SOCKET_BUFFER_SIZE,
    HEADER_FORMAT,
)

# Try to load the Bluetooth library.
# If it's not installed, we set a flag so we can show a helpful
# error message rather than a confusing Python crash.

import socket

# ================================================================
#  MAIN FUNCTION: send_file()
#
#  This does the actual work of sending a file.
#  It's written as a separate function (not just code at the top)
#  so our test file can call it directly without Bluetooth hardware.
# ================================================================

def send_file(sock, filepath, chunk_size=CHUNK_SIZE):
    """
    Send one file through an open socket connection.

    How it works:
      1. Check the file exists
      2. Send 8 bytes telling the receiver how big the file is
      3. Read the file in chunks and send each chunk

    sock       = the open connection to send through
    filepath   = the full path to the image file (e.g. "photo.jpg")
    chunk_size = how many bytes to send at a time (default: 64 KB)

    Returns True if the whole file was sent, False if something went wrong.
    """

    # --- Check the file actually exists -----------------------
    #
    #  os.path.exists() returns True if the file is found,
    #  False if it's missing.  We stop early if it's not there —
    #  no point trying to open a file that doesn't exist.
    #
    if not os.path.exists(filepath):
        print(f"[ERROR] Cannot find the file: {filepath}")
        print("        Double-check the IMAGE_PATH setting in config.py")
        return False   # False = something went wrong, tell the caller


    # --- Get the file size ------------------------------------
    #
    #  os.path.getsize() reads how many bytes the file is.
    #  For a 15 MB image, this will be around 15,728,640 bytes.
    #
    file_size = os.path.getsize(filepath)

    # os.path.basename() strips the folder path and gives just the filename.
    # e.g.  "/home/pi/Pictures/photo.jpg"  becomes  "photo.jpg"
    filename = os.path.basename(filepath)

    print(f"[SEND] File     : {filename}")
    print(f"[SEND] Size     : {file_size:,} bytes  ({file_size / 1024 / 1024:.2f} MB)")
    print(f"[SEND] Chunk    : {chunk_size // 1024} KB per chunk")
    print(f"[SEND] Chunks   : ~{file_size // chunk_size + 1} total")
    print()


    # --- Step 1: Send the file size as an 8-byte header -------
    #
    #  Before we send any image data, we send 8 bytes to tell
    #  the receiver "the file is exactly X bytes long."
    #
    #  struct.pack('>Q', file_size) converts the number into
    #  exactly 8 raw bytes.  Example: 15,728,640 becomes
    #  the bytes:  00 00 00 00 00 EF 00 00
    #
    #  The receiver reads these 8 bytes first and uses the number
    #  to know when it has received the complete file.
    #
    header = struct.pack(HEADER_FORMAT, file_size)
    sock.send(header)   # send those 8 bytes


    # --- Step 2: Send the image in chunks ---------------------
    #
    #  We open the file in binary read mode ('rb').
    #  Images are not text — they're raw bytes — so we must use
    #  'rb' not just 'r'.  Using 'r' would corrupt the file.
    #
    bytes_sent = 0
    start_time = time.time()   # note the time so we can calculate speed later

    with open(filepath, 'rb') as image_file:

        while True:

            # Read the next chunk from disk.
            # If the file has less than chunk_size bytes left,
            # .read() just returns however many are left.
            # When the file is finished, .read() returns b'' (empty).
            chunk = image_file.read(chunk_size)

            # b'' (empty bytes) means we've reached the end of the file.
            if not chunk:
                break   # exit the while loop — we're done!

            # Send this chunk over the Bluetooth connection.
            # sock.send() pushes these bytes to the laptop.
            sock.send(chunk)

            # Add this chunk's size to our running total.
            bytes_sent += len(chunk)

            # Show the user how far along we are.
            _show_progress(bytes_sent, file_size)


    # --- Finished! Show a summary -----------------------------

    # Calculate how many seconds the transfer took.
    elapsed = time.time() - start_time

    # Calculate the speed in KB/s.
    # Avoid division by zero if the transfer was instant (unlikely but safe).
    speed_kb = (bytes_sent / 1024) / elapsed if elapsed > 0 else 0

    print()   # move to a new line after the progress bar
    print(f"[DONE] Sent {bytes_sent:,} bytes in {elapsed:.1f} seconds")
    print(f"[DONE] Average speed: {speed_kb:.0f} KB/s  ({speed_kb/1024:.2f} MB/s)")

    return True   # True = everything worked fine


# ================================================================
#  HELPER FUNCTION: _show_progress()
#
#  Prints a progress bar that updates in-place on the same line.
#  The underscore at the start (_) is a Python convention meaning
#  "this is a helper — only used inside this file."
# ================================================================

def _show_progress(bytes_done, bytes_total):
    """
    Print a one-line progress bar that rewrites itself.

    Example output:
      [████████████░░░░░░░░]  60%   9.0/15.0 MB
    """

    # Calculate how far through we are as a percentage (0–100).
    percent = int(bytes_done / bytes_total * 100)

    # Build the bar: 20 characters wide.
    # filled = how many '█' to draw.
    # The rest are '░' (empty slots).
    filled = int(percent / 5)
    bar = '█' * filled + '░' * (20 - filled)

    # Convert bytes to megabytes — easier to read for large files.
    done_mb  = bytes_done  / 1024 / 1024
    total_mb = bytes_total / 1024 / 1024

    # end='\r' means "go back to the start of the same line"
    # instead of starting a new line.  This makes the bar update
    # in place rather than printing 240 separate lines.
    print(f"\r  [{bar}] {percent:3d}%  {done_mb:6.1f}/{total_mb:.1f} MB",
          end='', flush=True)


# ================================================================
#  ENTRY POINT
#
#  This block only runs when you execute this file directly:
#    python3 pi_sender.py
#
#  It does NOT run if another script imports this file.
#  That's what  if __name__ == "__main__":  checks.
# ================================================================

if __name__ == "__main__":

    # --- Check the user set a real MAC address ----------------
    #
    #  If they forgot to edit config.py, LAPTOP_MAC will still
    #  be the placeholder "XX:XX:XX:XX:XX:XX".  Catch that here.
    #
    if LAPTOP_MAC == "XX:XX:XX:XX:XX:XX":
        print("[ERROR] You haven't set your laptop's Bluetooth address yet!")
        print()
        print("  Fix: open config.py and replace XX:XX:XX:XX:XX:XX")
        print("       with your actual laptop MAC address.")
        exit(1)


    # --- Check the image file exists --------------------------
    if not os.path.exists(IMAGE_PATH):
        print(f"[ERROR] Image file not found: {IMAGE_PATH}")
        print()
        print("  Fix: open config.py and set IMAGE_PATH to the")
        print("       correct path to your photo.")
        exit(1)


    # --- Print a summary of what we're about to do ------------
    print("=" * 54)
    print("  Raspberry Pi  →  Laptop  |  Bluetooth Image Sender")
    print("=" * 54)
    print(f"  Laptop address : {LAPTOP_MAC}")
    print(f"  Channel        : {BLUETOOTH_PORT}")
    print(f"  Image to send  : {IMAGE_PATH}")
    print(f"  File size      : {os.path.getsize(IMAGE_PATH) / 1024 / 1024:.2f} MB")
    print()


    # --- Create the Bluetooth socket --------------------------
    #
    #  A socket is like a telephone — you create it, then "dial"
    #  a number to connect to someone.
    #
    #  bluetooth.RFCOMM is the protocol we use — it turns the
    #  Bluetooth radio into something that behaves like a cable,
    #  which is perfect for streaming a file.
    #
    print("[INFO] Setting up Bluetooth connection ...")
    sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
    # Make the send buffer larger so we can keep the Bluetooth
    # radio busy when sending a big file.
    # SOL_SOCKET and SO_SNDBUF are standard socket option codes.
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, SOCKET_BUFFER_SIZE)


    # --- Connect to the laptop --------------------------------
    #
    #  .connect() takes a tuple of (MAC address, channel number).
    #  It will pause the program here until the laptop answers
    #  or the attempt fails.
    #
    try:
        print(f"[INFO] Connecting to {LAPTOP_MAC} on channel {BLUETOOTH_PORT} ...")
        print("       (Make sure laptop_receiver.py is running on the laptop!)")
        sock.connect((LAPTOP_MAC, BLUETOOTH_PORT))
        print("[INFO] Connected!\n")

    except OSError as error:
        # OSError means the connection failed.
        # Common reasons:
        #   - The laptop isn't running laptop_receiver.py
        #   - Wrong MAC address in config.py
        #   - Devices aren't paired
        #   - Too far apart
        print(f"\n[ERROR] Could not connect: {error}")
        print()
        print("  Check:")
        print("    1. Is laptop_receiver.py running on the laptop?")
        print("    2. Is LAPTOP_MAC correct in config.py?")
        print("    3. Are the devices paired in Bluetooth settings?")
        print("    4. Are the devices within ~10 metres of each other?")
        sock.close()   # always close the socket to free up resources
        exit(1)


    # --- Send the image ---------------------------------------
    transfer_ok = send_file(sock, IMAGE_PATH)


    # --- Small pause before disconnecting --------------------
    #
    #  We wait half a second to make sure the laptop has finished
    #  writing the last chunk to disk before we close the connection.
    #
    time.sleep(0.5)


    # --- Close the connection ---------------------------------
    #
    #  Always close the socket when you're finished.
    #  This tells the laptop "I'm done" and frees up
    #  the Bluetooth hardware for other programs.
    #
    sock.close()
    print("[INFO] Bluetooth connection closed.")

    # Print final result
    if transfer_ok:
        print("\n✓  Transfer complete!  Check the bluetooth_received folder on your laptop.")
    else:
        print("\n✗  Transfer failed.  See the error messages above.")
