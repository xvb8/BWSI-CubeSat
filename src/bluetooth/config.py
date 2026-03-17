# ================================================================
#  config.py  —  YOUR SETTINGS FILE
#
#  This is the ONLY file you need to edit before running.
#  The sender and receiver both read from here automatically,
#  so changing a value here changes it everywhere at once.
# ================================================================


# ---------------------------------------------------------------
#  STEP 1 — Enter your laptop's Bluetooth address
# ---------------------------------------------------------------
#
#  A MAC address is a unique ID for every Bluetooth device.
#  It looks like six pairs of letters/numbers:  A1:B2:C3:D4:E5:F6 
#
#  How to find YOUR laptop's Bluetooth MAC address:
#
#    Windows → Settings → Bluetooth & devices
#              → "More Bluetooth settings" → Hardware tab
#              → Look for "Device Address"
#
#    Mac     → Apple menu → About This Mac → System Report → Bluetooth
#              → Look for "Bluetooth Low Energy MAC"
#
#    Linux   → Open a terminal, type:  hciconfig
#              → Look for "BD Address"
#
with open("src/bluetooth/mac_address.txt", "r") as f:
    LAPTOP_MAC = f.read().strip()   # <-- Paste your laptop's address here


# ---------------------------------------------------------------
#  STEP 2 — Choose a Bluetooth channel number
# ---------------------------------------------------------------
#
#  Think of this like a walkie-talkie channel.
#  Both the Pi (sender) and laptop (receiver) must be on the
#  same channel, or they won't be able to hear each other.
#
#  Valid channels are 1 to 30.
#  Leave this as 7 unless you have a specific reason to change it.
#
BLUETOOTH_PORT = 7


# ---------------------------------------------------------------
#  STEP 3 — Enter the path to the image you want to send
# ---------------------------------------------------------------
#
#  This is the photo file sitting on your Raspberry Pi.
#
#  Examples:
#    "photo.jpg"                           (file is in the same folder as the script)
#    "/home/pi/Pictures/holiday.jpg"       (full path to the file)
#    "/home/pi/Desktop/big_photo.png"      (PNG, BMP, TIFF — all work, not just JPG)
#
#  For a 15 MB uncompressed file, a BMP or PNG without compression
#  is fine — this program sends whatever bytes are in the file,
#  so it doesn't matter what image format you use.
#
IMAGE_PATH = "/BWSI-CubeSat/images/KaranK_154137.jpg"   # <-- Change this to your image filename


# ---------------------------------------------------------------
#  STEP 4 — Choose where received images are saved on your laptop
# ---------------------------------------------------------------
#
#  When the laptop receives a photo, it saves it here.
#  The folder is created for you automatically if it doesn't exist.
#
#  os.path.expanduser("~") gives us the home folder of whoever
#  is logged in, so this works on any machine without hardcoding
#  a username.
#
import os
SAVE_FOLDER = os.path.join(os.path.expanduser("~"), "bluetooth_received")
#
#  Result:
#    Windows  →  C:\Users\YourName\bluetooth_received
#    Mac/Linux→  /home/yourname/bluetooth_received


# ================================================================
#  ADVANCED SETTINGS
#  These are already tuned for 15 MB+ transfers.
#  You don't need to change them, but explanations are below.
# ================================================================

# --- Chunk size ------------------------------------------------
#
#  Data is sent in pieces called "chunks" rather than all at once.
#  (Sending 15 MB in one go would crash most systems.)
#
#  Think of it like moving house:
#    Small box  (4 KB)  = many trips, slow
#    Big box   (64 KB)  = fewer trips, ~18x faster for large files
#
#  65,536 bytes = 64 KB per chunk.
#  Benchmarked at ~250+ MB/s on loopback; real Bluetooth tops out
#  around 2–3 MB/s, so this chunk size keeps the radio 100% busy
#  and wastes no time.
#
CHUNK_SIZE = 65536   # 64 KB — best balance for 15 MB+ transfers


# --- Socket buffer size ----------------------------------------
#
#  Before bytes travel over Bluetooth, they wait in a small
#  memory area called a "buffer" — like a loading dock.
#  A bigger buffer means the program can keep filling the
#  Bluetooth radio without stopping to wait.
#
#  262,144 bytes = 256 KB.
#  This is 4x the chunk size, so there's always room for
#  several chunks waiting to go — no pauses mid-transfer.
#
SOCKET_BUFFER_SIZE = 262144   # 256 KB send/receive buffer


# --- File-size header ------------------------------------------
#
#  The very first thing the sender transmits is a tiny 8-byte
#  message that says "the file is exactly X bytes long."
#  The receiver reads those 8 bytes first so it knows exactly
#  when the file is finished — otherwise it would keep waiting
#  forever not knowing if more data is coming.
#
#  '>Q' is the code for "8-byte big-endian unsigned integer".
#  You never need to change these two lines.
#
HEADER_FORMAT = '>Q'
HEADER_SIZE   = 8

# --- Filename-length header ------------------------------------
#
#  Right after the 8-byte file-size header, the sender transmits
#  a 2-byte value that tells the receiver how long the filename is,
#  followed by that many UTF-8 bytes of filename.  This lets the
#  receiver save the file with the correct extension (.jpg, .zip, etc.).
#
#  '>H' is the code for "2-byte big-endian unsigned short" (max 65535).
#
NAME_LEN_FORMAT = '>H'
NAME_LEN_SIZE   = 2

# --- Message type prefix ---------------------------------------
#
#  Every message over the socket starts with a single byte that
#  tells the receiver what kind of message is coming next:
#
#    MSG_NOTIFICATION (0x01) — a short text notification
#        (2-byte length + UTF-8 text)
#    MSG_FILE (0x02) — a full file transfer
#        (existing protocol: 8-byte size + 2-byte name len + name + data)
#
MSG_NOTIFICATION = b'\x01'
MSG_FILE         = b'\x02'
MSG_TYPE_SIZE    = 1
