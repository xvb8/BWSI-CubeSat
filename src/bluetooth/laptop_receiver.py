# ================================================================
#  laptop_receiver.py  —  Runs on your Laptop
#
#  This script listens for a Bluetooth connection from your Pi
#  and saves every photo it receives into a folder.
#  It handles large files (15 MB and above) without any problems.
#
#  BEFORE YOU RUN THIS:
#    1. Start THIS script on the laptop FIRST
#    2. Then run pi_sender.py on the Pi
#
#  RUN:
#    python laptop_receiver.py
#
#  STOP:
#    Press Ctrl+C at any time.
# ================================================================
# Use "add device on laptop" to pair your Pi and laptop over Bluetooth first.
# Then run this script on the laptop, and pi_sender.py on the Pi.


# --- What these imports do ------------------------------------
#
#  'os'       — lets us create folders and build file paths
#  'struct'   — turns 8 raw bytes back into a number (the file size)
#  'datetime' — lets us put the current date & time in filenames
#               so we never accidentally overwrite an old photo
#
import os
import struct
from datetime import datetime

from config import (
    BLUETOOTH_PORT,
    SAVE_FOLDER,
    CHUNK_SIZE,
    SOCKET_BUFFER_SIZE,
    HEADER_FORMAT,
    HEADER_SIZE,
    NAME_LEN_FORMAT,
    NAME_LEN_SIZE,
    MSG_NOTIFICATION,
    MSG_FILE,
    MSG_TYPE_SIZE,
)

import socket

with open("src/bluetooth/mac_address.txt", "r") as f:
    MAC_ADDRESS = f.read().strip()



# ================================================================
#  MAIN FUNCTION: receive_file()
#
#  This does the actual work of receiving a file.
#  Written as a separate function so our test suite can call it
#  without needing real Bluetooth hardware.
# ================================================================

def receive_file(client_sock, save_folder=SAVE_FOLDER, chunk_size=CHUNK_SIZE):
    """
    Receive one file from an open connection and save it to disk.

    How it works:
      1. Read the 8-byte header to find out how big the file is
      2. Keep reading chunks until we've received that many bytes
      3. Save everything to a new file in save_folder

    client_sock = the open connection from the Pi
    save_folder = folder on this computer where the file will be saved
    chunk_size  = how many bytes to read at a time (default: 64 KB)

    Returns the path of the saved file if successful, or None if it failed.
    """

    # --- Step 1: Read the 8-byte file-size header -------------
    #
    #  The sender always sends 8 bytes first.
    #  Those 8 bytes encode the total size of the file.
    #  We must read them before any image data arrives.
    #
    #  We use _receive_exact() rather than just recv() because
    #  the network might split even these 8 bytes across multiple
    #  deliveries.  _receive_exact() keeps reading until it has all 8.
    #
    raw_header = _receive_exact(client_sock, HEADER_SIZE)

    # If raw_header is None, the connection closed before we got the header.
    if raw_header is None:
        print("[ERROR] Connection closed before the file size arrived.")
        print("        Was pi_sender.py stopped early?")
        return None

    # struct.unpack converts the 8 raw bytes back into a Python integer.
    # It returns a tuple like (15728640,) so we use [0] to get just the number.
    file_size = struct.unpack(HEADER_FORMAT, raw_header)[0]

    # --- Step 1b: Read the filename ---------------------------
    #
    #  The sender transmits a 2-byte length followed by a UTF-8
    #  filename.  We use the extension to save the file correctly
    #  (.jpg, .zip, etc.).
    #
    raw_name_len = _receive_exact(client_sock, NAME_LEN_SIZE)
    if raw_name_len is None:
        print("[ERROR] Connection closed before the filename arrived.")
        return None

    name_len = struct.unpack(NAME_LEN_FORMAT, raw_name_len)[0]
    raw_name = _receive_exact(client_sock, name_len)
    if raw_name is None:
        print("[ERROR] Connection closed while reading the filename.")
        return None

    original_name = raw_name.decode('utf-8')
    _, ext = os.path.splitext(original_name)

    print(f"[RECV] File name : {original_name}")
    print(f"[RECV] File size : {file_size:,} bytes  ({file_size / 1024 / 1024:.2f} MB)")
    print(f"[RECV] Chunk     : {chunk_size // 1024} KB per chunk")
    print(f"[RECV] Expecting : ~{file_size // chunk_size + 1} chunks")
    print()


    # --- Build the output filename ----------------------------
    #
    #  We add a timestamp to each filename so files are never
    #  overwritten if you send multiple photos.
    #  The extension comes from the sender so the file type is correct.
    #
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path  = os.path.join(save_folder, f"received_{timestamp}{ext}")


    # --- Step 2: Receive the image bytes and write to disk ----
    #
    #  We open the output file in binary write mode ('wb').
    #  'wb' means: create (or overwrite) the file, write raw bytes.
    #  Never use just 'w' for images — that's text mode and will
    #  corrupt the photo.
    #
    bytes_received = 0

    with open(out_path, 'wb') as output_file:

        while bytes_received < file_size:

            # How many bytes are still missing?
            remaining = file_size - bytes_received

            # We ask for at most chunk_size bytes.
            # But if fewer bytes are left than chunk_size,
            # we only ask for what's left (don't read past the end).
            to_read = min(chunk_size, remaining)

            # Receive the next chunk from the Pi.
            chunk = client_sock.recv(to_read)

            # An empty result means the connection dropped unexpectedly.
            if not chunk:
                print("\n[ERROR] Connection lost in the middle of the transfer!")
                print(f"        Only received {bytes_received:,} of {file_size:,} bytes.")
                print("        The saved file will be incomplete and corrupted.")
                return None

            # Write this chunk straight to disk.
            output_file.write(chunk)

            # Track how many bytes we've received so far.
            bytes_received += len(chunk)

            # Update the progress bar on screen.
            _show_progress(bytes_received, file_size)


    # --- Finished! -------------------------------------------

    print()   # move to a new line after the progress bar
    print(f"[DONE] Saved to: {out_path}")
    return out_path   # return the file path so the caller can use it


# ================================================================
#  HELPER FUNCTION: _receive_exact()
#
#  Reads EXACTLY n bytes from a socket — no more, no less.
#
#  Why do we need this?
#  When you call sock.recv(8), the OS might only give you 3 bytes
#  right now and the other 5 bytes a moment later.  This is normal
#  behaviour called "fragmentation."  recv() doesn't guarantee you
#  get all the bytes you asked for in one call.
#
#  _receive_exact() keeps calling recv() in a loop until the full
#  n bytes have arrived.
# ================================================================

def _receive_exact(sock, n):
    """
    Keep reading from sock until exactly n bytes have been received.
    Returns the bytes if successful, or None if the connection closed early.
    """
    # Start with an empty byte string.
    # We'll keep adding to it until it's n bytes long.
    buffer = b""

    while len(buffer) < n:
        # Ask for however many bytes are still missing.
        still_needed = n - len(buffer)
        packet = sock.recv(still_needed)

        # Empty packet = connection closed before we got everything.
        if not packet:
            return None

        # Add these bytes to our collection.
        buffer += packet

    return buffer   # we now have exactly n bytes


# ================================================================
#  HELPER FUNCTION: _show_progress()
#
#  Prints a progress bar that updates in place on the same line.
# ================================================================

def _show_progress(bytes_done, bytes_total):
    """
    Print a one-line progress bar:
      [████████████░░░░░░░░]  60%   9.0/15.0 MB
    """
    percent = int(bytes_done / bytes_total * 100)
    filled  = int(percent / 5)
    bar     = '█' * filled + '░' * (20 - filled)
    done_mb  = bytes_done  / 1024 / 1024
    total_mb = bytes_total / 1024 / 1024

    # \r moves the cursor back to the start of the line so the
    # next print overwrites this one — that's what makes it animate.
    print(f"\r  [{bar}] {percent:3d}%  {done_mb:6.1f}/{total_mb:5.1f} MB",
          end='', flush=True)


# ================================================================
#  ENTRY POINT  —  runs when you do:  python src/bluetooth/laptop_receiver.py
# ================================================================

    # --- Create the save folder if it doesn't exist yet -------
    #
    #  os.makedirs() creates the folder.
    #  exist_ok=True means "don't complain if it already exists."
    #
if __name__ == "__main__":
    os.makedirs(SAVE_FOLDER, exist_ok=True)


    # --- Print a startup summary ------------------------------
    print("=" * 54)
    print("  Laptop  |  Bluetooth Image Receiver")
    print("=" * 54)
    print(f"  Listening on channel : {BLUETOOTH_PORT}")
    print(f"  Saving files to      : {SAVE_FOLDER}")
    print(f"  Chunk size           : {CHUNK_SIZE // 1024} KB")
    print(f"  Socket buffer        : {SOCKET_BUFFER_SIZE // 1024} KB")
    print()


    # --- Create the server socket -----------------------------
    #
    #  This socket is the "front door" — it waits for the Pi to
    #  knock, then opens a new connection specifically for that Pi.
    #
    server_sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
    server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, SOCKET_BUFFER_SIZE)
    server_sock.bind((MAC_ADDRESS, BLUETOOTH_PORT))  # MAC_ADDRESS is already read at the top
    server_sock.listen(1)

    print("[READY] Waiting for the Raspberry Pi to connect ...")
    print("        (Now run pi_sender.py on the Pi)")
    print("        Press Ctrl+C at any time to stop.\n")


    # --- Main loop: keep accepting connections ----------------
    #
    #  This loop runs forever, handling one connection at a time.
    #  Each time the Pi connects, we receive the photo and then
    #  go back to waiting for the next one.
    #
    try:
        while True:

            # .accept() PAUSES HERE and waits.
            # When the Pi connects, it returns:
            #   client_sock — a new socket just for this Pi session
            #   client_addr — the Pi's Bluetooth MAC address
            client_sock, client_addr = server_sock.accept()
            client_sock.settimeout(300)


            print(f"[INFO] Pi connected from {client_addr}")

            # Enlarge the receive buffer on the per-connection socket too.
            client_sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, SOCKET_BUFFER_SIZE)

            # --- Message loop: handle notifications and file transfers ---
            #
            #  The Pi may send multiple messages over one connection:
            #    - Notifications (e.g. "Photo taken") before the file
            #    - Exactly one file transfer at the end
            #
            #  Each message starts with a 1-byte type indicator.
            #
            saved_path = None
            while True:
                msg_type = _receive_exact(client_sock, MSG_TYPE_SIZE)
                if msg_type is None:
                    # Connection closed — Pi is done.
                    break

                if msg_type == MSG_NOTIFICATION:
                    # Read 2-byte length + UTF-8 message text
                    raw_len = _receive_exact(client_sock, NAME_LEN_SIZE)
                    if raw_len is None:
                        break
                    msg_len = struct.unpack(NAME_LEN_FORMAT, raw_len)[0]
                    raw_msg = _receive_exact(client_sock, msg_len)
                    if raw_msg is None:
                        break
                    print(f"[PI] {raw_msg.decode('utf-8')}")

                elif msg_type == MSG_FILE:
                    # Full file transfer follows (existing protocol).
                    saved_path = receive_file(client_sock)
                    # After a file transfer the Pi shuts down the socket,
                    # so we break out of the message loop.
                    break

                else:
                    print(f"[WARN] Unknown message type: {msg_type!r}")
                    break

            # Close the connection with this Pi.
            # This does NOT shut down the server — we loop back
            # to .accept() and wait for the next connection.
            client_sock.close()

            if saved_path:
                print(f"\n✓  Photo saved successfully!\n")
            elif saved_path is None and msg_type is None:
                print(f"\n[INFO] Pi disconnected.\n")
            else:
                print(f"\n✗  Transfer failed — file may be incomplete.\n")

            print("[READY] Waiting for next connection ...\n")


    except KeyboardInterrupt:
        # Ctrl+C was pressed — graceful shutdown.
        # KeyboardInterrupt is the Python exception for Ctrl+C.
        print("\n[INFO] Stopped by user (Ctrl+C).")

    finally:
        # 'finally' always runs no matter what —
        # even if there was a crash.  This ensures we
        # always clean up the socket properly.
        server_sock.close()
        print("[INFO] Bluetooth server closed.  Goodbye!")
