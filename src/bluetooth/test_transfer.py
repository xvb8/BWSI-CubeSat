# ================================================================
#  test_transfer.py  —  Test Suite
#
#  This file checks that every part of the transfer code works
#  correctly — WITHOUT needing real Bluetooth hardware.
#
#  HOW THE TESTS WORK (no Bluetooth needed!)
#  -----------------------------------------
#  The send_file() and receive_file() functions work with any
#  socket object — Bluetooth or plain network.
#
#  So instead of Bluetooth, we use a "loopback" connection:
#  data sent to 127.0.0.1 (your own computer's IP address)
#  goes out through a pretend network and straight back in.
#  The send/receive logic is 100% identical.
#
#  It's like testing a postal system by posting a letter from
#  one room to another room in the same building.
#
#  RUN ALL TESTS:
#    python3 src/bluetooth/test_transfer.py
#
#  A ✓ PASS means that test worked correctly.
#  A ✗ FAIL means something is broken — read the message.
# ================================================================


import hashlib      # for calculating MD5 checksums (file fingerprints)
import os           # for creating files and folders
import struct       # for building/reading the 8-byte size header
import sys          # for sys.path (so Python can find our scripts)
import tempfile     # for creating temporary folders that auto-delete
import threading    # for running sender and receiver at the same time
import time         # for pauses and timing
from pathlib import Path   # for working with file paths cleanly


# --- Make sure Python can find our scripts --------------------
#
#  sys.path is the list of folders Python searches when you
#  write  import something.
#  We add the folder containing this script so Python can find
#  pi_sender.py and laptop_receiver.py.
#
THIS_DIR = Path(__file__).parent
sys.path.insert(0, str(THIS_DIR))

# Import the two core functions we want to test.
from pi_sender       import send_file
from laptop_receiver import receive_file


# --- Colour codes for nicer terminal output -------------------
#
#  These are ANSI escape codes — special characters that tell
#  the terminal to change text colour.
#  \033[92m = green,  \033[91m = red,  \033[93m = yellow,  \033[0m = reset
#
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
RESET  = "\033[0m"
BOLD   = "\033[1m"

def ok(msg):    print(f"  {GREEN}✓ PASS{RESET}  {msg}")
def fail(msg):  print(f"  {RED}✗ FAIL{RESET}  {msg}")
def info(msg):  print(f"  {YELLOW}»{RESET}      {msg}")


# ================================================================
#  UTILITY: md5_of_file()
#
#  Calculates the MD5 "fingerprint" of a file.
#  If two files have the same MD5, their contents are identical —
#  not a single byte is different.
#  This is how we prove the photo wasn't corrupted in transit.
# ================================================================

def md5_of_file(path):
    """Return the MD5 hash of a file as a hex string (e.g. 'a3f2...')."""
    hasher = hashlib.md5()
    # Read in 64 KB chunks — safer than loading the whole file into RAM.
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            hasher.update(chunk)
    return hasher.hexdigest()


# ================================================================
#  UTILITY: make_test_image()
#
#  Creates a real image file we can use for testing.
#  Can produce any size from tiny to 15 MB+.
# ================================================================

def make_test_image(path, size_bytes=None, width=200, height=150):
    """
    Create a test image file at `path`.

    If size_bytes is given, the file will be exactly that many bytes
    (useful for a precise 15 MB test).

    Otherwise a JPEG of width x height is created using Pillow.
    Falls back to random bytes if Pillow isn't installed.
    """

    if size_bytes is not None:
        # Create a file of exactly size_bytes bytes filled with
        # a repeating pattern (not purely random — this compresses
        # better in tests, but still exercises the transfer logic).
        # We use a byte pattern that would never appear in real JPEG
        # header bytes, so it's clearly not a valid image — that's fine
        # for transfer testing; we only care about byte count and MD5.
        chunk = bytes(range(256)) * (size_bytes // 256) + bytes(range(size_bytes % 256))
        with open(path, 'wb') as f:
            f.write(chunk)
        return

    # Try to create a real colourful JPEG using Pillow.
    try:
        from PIL import Image, ImageDraw
        img = Image.new("RGB", (width, height))
        pixels = img.load()
        # Fill with a colour gradient so the image isn't all one colour.
        for y in range(height):
            for x in range(width):
                pixels[x, y] = (
                    int(255 * x / width),    # red channel increases left→right
                    int(255 * y / height),   # green channel increases top→bottom
                    128,                     # blue is constant
                )
        draw = ImageDraw.Draw(img)
        # Draw a white border and "TEST" label.
        draw.rectangle([4, 4, width - 4, height - 4], outline=(255, 255, 255), width=2)
        draw.text((width // 2 - 12, height // 2 - 6), "TEST", fill=(255, 255, 255))
        img.save(path, "JPEG", quality=85)
    except ImportError:
        # Pillow isn't installed — write minimal bytes that act as a file.
        with open(path, 'wb') as f:
            f.write(os.urandom(max(1024, width * height * 3 // 8)))


# ================================================================
#  UTILITY: run_loopback_transfer()
#
#  Simulates a full Pi→Laptop transfer over localhost (127.0.0.1).
#
#  How it works:
#    1. Start a "receiver" thread that opens a TCP server on localhost
#    2. Call send_file() (the sender) from the main thread
#    3. The two sides talk over a loopback network connection
#    4. Return the path of the saved file
#
#  This exercises send_file() and receive_file() together — the
#  exact same code that runs over real Bluetooth, just through
#  a different socket type.
# ================================================================

def run_loopback_transfer(src_path, dst_folder, tcp_port, chunk_size=65536):
    """
    Run a full transfer cycle (send + receive) over localhost TCP.
    Returns (saved_file_path, error_message).
    saved_file_path is None if the transfer failed.
    """
    import socket

    # A dict to pass results out of the receiver thread.
    # (Python threads can't return values directly, so we use a dict.)
    result = {"path": None, "error": None}

    # threading.Event is like a flag:
    #   server_ready.set()   → raise the flag (server is listening)
    #   server_ready.wait()  → pause until the flag is raised
    server_ready = threading.Event()

    # --- Receiver thread (runs in background) -----------------
    def receiver_thread():
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("127.0.0.1", tcp_port))
        server.listen(1)
        server.settimeout(30)       # give up after 30 seconds if nobody connects
        server_ready.set()          # signal: "I'm listening, sender can connect now"
        try:
            conn, _ = server.accept()
            saved = receive_file(conn, save_folder=dst_folder, chunk_size=chunk_size)
            result["path"] = saved
            conn.close()
        except Exception as e:
            result["error"] = str(e)
        finally:
            server.close()

    # Start the receiver running in the background.
    t = threading.Thread(target=receiver_thread, daemon=True)
    t.start()

    # Wait until the receiver is ready before the sender tries to connect.
    server_ready.wait(timeout=10)

    # --- Sender (runs in main thread) -------------------------
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client.settimeout(60)   # allow up to 60 seconds for a large transfer
    client.connect(("127.0.0.1", tcp_port))
    send_file(client, src_path, chunk_size=chunk_size)
    client.close()

    # Wait for the receiver thread to finish writing the file.
    t.join(timeout=60)

    return result["path"], result["error"]


# ================================================================
#  TEST RUNNER CLASS
#
#  Each method starting with  test_  is one test.
#  run_all() calls them all and counts passes/failures.
# ================================================================

class TestRunner:

    def __init__(self):
        self.passed = 0    # count of tests that passed
        self.failed = 0    # count of tests that failed
        self._port  = 59900   # base port number; each test uses a different one

    def next_port(self):
        """Return the next available TCP port number."""
        self._port += 1
        return self._port

    def run_all(self):
        print(f"\n{BOLD}{'=' * 58}{RESET}")
        print(f"{BOLD}  Bluetooth Transfer — Test Suite{RESET}")
        print(f"{BOLD}{'=' * 58}{RESET}\n")

        self.test_header_encoding()
        self.test_receive_exact_fragmented()
        self.test_missing_file_graceful()
        self.test_small_jpeg()
        self.test_large_jpeg()
        self.test_15mb_uncompressed()      # ← the important one
        self.test_tiny_chunk_size()
        self.test_byte_perfect_integrity()
        self.test_multiple_sequential()
        self.test_progress_edge_cases()

        # --- Final summary ------------------------------------
        print(f"\n{BOLD}{'─' * 58}{RESET}")
        total  = self.passed + self.failed
        colour = GREEN if self.failed == 0 else RED
        print(f"{BOLD}  {colour}{self.passed}/{total} tests passed{RESET}")
        if self.failed:
            print(f"  {RED}{self.failed} test(s) FAILED — see messages above{RESET}")
        print(f"{BOLD}{'─' * 58}{RESET}\n")
        return self.failed == 0


    # ============================================================
    #  TEST 1: The 8-byte size header must survive a round trip
    #
    #  We pack a number into 8 bytes, then unpack it and check
    #  we get the same number back.  We test several sizes
    #  including 15 MB and values larger than 4 GB.
    # ============================================================
    def test_header_encoding(self):
        print(f"{BOLD}[1] 8-byte size header round-trip{RESET}")
        fmt = '>Q'

        # These are the sizes we test, in bytes.
        sizes = [0, 1, 4096, 15_728_640, 100_000_000, 2**32, 2**40]

        for size in sizes:
            packed   = struct.pack(fmt, size)     # number → 8 bytes
            unpacked = struct.unpack(fmt, packed)[0]   # 8 bytes → number

            # The packed header must always be exactly 8 bytes.
            if len(packed) != 8:
                fail(f"Header is {len(packed)} bytes, expected 8 — for size {size:,}")
                self.failed += 1
                continue

            # The unpacked number must exactly equal the original.
            if unpacked == size:
                ok(f"{size:>15,} bytes → {packed.hex()} → {unpacked:,}")
                self.passed += 1
            else:
                fail(f"Round-trip failed: {size} → packed → {unpacked}")
                self.failed += 1


    # ============================================================
    #  TEST 2: _receive_exact() must handle fragmented delivery
    #
    #  Networks sometimes split data into pieces.  Even 8 bytes
    #  might arrive as 3 bytes then 5 bytes.  This tests that
    #  _receive_exact() keeps reading until it has all 8.
    # ============================================================
    def test_receive_exact_fragmented(self):
        print(f"\n{BOLD}[2] _receive_exact handles fragmented delivery{RESET}")
        import socket
        from laptop_receiver import _receive_exact

        # socket.socketpair() creates two connected sockets.
        # Anything sent into 'a' comes out of 'b', and vice versa.
        a, b = socket.socketpair()

        original = b"HELLO_WORLD_12345"   # 17 bytes

        # Send the 17 bytes in three separate pieces: 5, 7, 5.
        # This simulates a fragmented network delivery.
        a.send(original[:5])
        a.send(original[5:12])
        a.send(original[12:])

        # _receive_exact should assemble all three pieces into the original.
        result = _receive_exact(b, len(original))
        a.close()
        b.close()

        if result == original:
            ok("17 bytes sent in 3 fragments → assembled correctly")
            self.passed += 1
        else:
            fail(f"Expected {original!r}, got {result!r}")
            self.failed += 1


    # ============================================================
    #  TEST 3: Missing file must fail gracefully (no crash)
    #
    #  If someone puts the wrong path in config.py, the program
    #  should print a helpful error — not crash with a traceback.
    # ============================================================
    def test_missing_file_graceful(self):
        print(f"\n{BOLD}[3] Missing file returns False without crashing{RESET}")
        import socket
        a, b = socket.socketpair()
        try:
            result = send_file(b, "/does/not/exist/photo.jpg")
            if result is False:
                ok("send_file() returned False — no crash")
                self.passed += 1
            else:
                fail(f"Expected False, got {result!r}")
                self.failed += 1
        except Exception as e:
            fail(f"Crashed with: {e}")
            self.failed += 1
        finally:
            a.close()
            b.close()


    # ============================================================
    #  TEST 4: Transfer a small JPEG (~4 KB)
    # ============================================================
    def test_small_jpeg(self):
        print(f"\n{BOLD}[4] Small JPEG transfer (200×150 px){RESET}")
        self._image_transfer_test("small", width=200, height=150,
                                  port=self.next_port())


    # ============================================================
    #  TEST 5: Transfer a larger JPEG (~80 KB)
    # ============================================================
    def test_large_jpeg(self):
        print(f"\n{BOLD}[5] Large JPEG transfer (1920×1080 px){RESET}")
        self._image_transfer_test("large", width=1920, height=1080,
                                  port=self.next_port())


    # ============================================================
    #  TEST 6: Transfer a 15 MB UNCOMPRESSED file
    #
    #  This is the most important test.
    #  A 15 MB file forces all of the following:
    #   - Many chunks (15 MB ÷ 64 KB = ~240 iterations of the loop)
    #   - The progress bar must update hundreds of times without crashing
    #   - All 15,728,640 bytes must arrive intact (verified with MD5)
    #
    #  We create the file as raw bytes (not a JPEG) so the size is
    #  exact — "uncompressed" means no JPEG compression shrinks it.
    # ============================================================
    def test_15mb_uncompressed(self):
        print(f"\n{BOLD}[6] ★ 15 MB UNCOMPRESSED PHOTO TRANSFER ★{RESET}")
        TARGET_SIZE = 15 * 1024 * 1024   # exactly 15,728,640 bytes

        with tempfile.TemporaryDirectory() as tmpdir:
            src = os.path.join(tmpdir, "photo_15mb.bin")
            dst = os.path.join(tmpdir, "received")
            os.makedirs(dst)

            # Create a 15 MB test file.
            info(f"Creating {TARGET_SIZE:,} byte ({TARGET_SIZE/1024/1024:.0f} MB) test file ...")
            make_test_image(src, size_bytes=TARGET_SIZE)

            actual_size = os.path.getsize(src)
            src_md5     = md5_of_file(src)

            info(f"Source file: {actual_size:,} bytes  MD5={src_md5}")

            # Run the transfer.
            start    = time.time()
            saved, err = run_loopback_transfer(src, dst, self.next_port())
            elapsed  = time.time() - start

            if err:
                fail(f"Transfer error: {err}")
                self.failed += 1
                return

            if not saved or not os.path.exists(saved):
                fail("receive_file() returned None — file was not saved")
                self.failed += 1
                return

            received_size = os.path.getsize(saved)
            received_md5  = md5_of_file(saved)

            info(f"Received   : {received_size:,} bytes  MD5={received_md5}")
            info(f"Time       : {elapsed:.1f}s")

            # Check 1: byte count must match exactly.
            if actual_size != received_size:
                fail(f"Size mismatch! Sent {actual_size:,} but received {received_size:,}")
                self.failed += 1
                return

            # Check 2: MD5 must match — proves no byte was changed.
            if src_md5 == received_md5:
                ok(f"All {received_size/1024/1024:.0f} MB received intact — MD5 matches!")
                self.passed += 1
            else:
                fail("MD5 mismatch — data was corrupted during transfer!")
                self.failed += 1


    # ============================================================
    #  TEST 7: Tiny 64-byte chunks — stress-tests the loop
    #
    #  Using 64-byte chunks means the send/receive loop runs
    #  hundreds of times even for a small file.
    #  This proves the loop logic is correct for any chunk size.
    # ============================================================
    def test_tiny_chunk_size(self):
        print(f"\n{BOLD}[7] Tiny 64-byte chunks — stress-tests the loop{RESET}")
        with tempfile.TemporaryDirectory() as tmpdir:
            src = os.path.join(tmpdir, "test.jpg")
            dst = os.path.join(tmpdir, "received")
            os.makedirs(dst)
            make_test_image(src, width=200, height=150)

            src_md5 = md5_of_file(src)
            info(f"File: {os.path.getsize(src):,} bytes, chunk=64 bytes, "
                 f"~{os.path.getsize(src)//64} iterations of the loop")

            saved, err = run_loopback_transfer(src, dst, self.next_port(), chunk_size=64)
            self._check_md5(saved, err, src_md5)


    # ============================================================
    #  TEST 8: Byte-perfect integrity with random data
    #
    #  We fill a file with random bytes, transfer it, and check
    #  every single byte is identical using MD5.
    #  Random data has no pattern, so we can't get lucky — every
    #  byte must be exactly right.
    # ============================================================
    def test_byte_perfect_integrity(self):
        print(f"\n{BOLD}[8] Byte-perfect integrity (100,000 random bytes){RESET}")
        with tempfile.TemporaryDirectory() as tmpdir:
            src = os.path.join(tmpdir, "random.bin")
            dst = os.path.join(tmpdir, "received")
            os.makedirs(dst)

            # os.urandom() generates truly random bytes.
            random_data = os.urandom(100_000)
            with open(src, 'wb') as f:
                f.write(random_data)

            src_md5 = md5_of_file(src)
            info(f"100,000 random bytes  MD5={src_md5}")

            saved, err = run_loopback_transfer(src, dst, self.next_port())

            if saved:
                recv_md5 = md5_of_file(saved)
                info(f"Received              MD5={recv_md5}")
                if src_md5 == recv_md5:
                    ok("Not a single byte was changed during transfer")
                    self.passed += 1
                else:
                    fail("MD5 mismatch — corruption detected!")
                    self.failed += 1
            else:
                fail(f"Transfer failed: {err}")
                self.failed += 1


    # ============================================================
    #  TEST 9: Three transfers back-to-back
    #
    #  Verifies there's no "state leakage" between transfers.
    #  Each photo should be independent — receiving photo 3
    #  shouldn't be affected by photo 1 or 2.
    # ============================================================
    def test_multiple_sequential(self):
        print(f"\n{BOLD}[9] Three sequential transfers — no state leakage{RESET}")
        src_hashes  = []
        recv_hashes = []

        with tempfile.TemporaryDirectory() as tmpdir:
            dst = os.path.join(tmpdir, "received")
            os.makedirs(dst)

            for i in range(3):
                src = os.path.join(tmpdir, f"photo_{i}.jpg")
                make_test_image(src, width=100 + i * 40, height=100 + i * 40)
                src_hashes.append(md5_of_file(src))
                info(f"Photo {i+1}: {os.path.getsize(src):,} bytes  MD5={src_hashes[-1]}")

                saved, _ = run_loopback_transfer(src, dst, self.next_port())
                recv_hashes.append(md5_of_file(saved) if saved else None)

        all_match = all(s == r for s, r in zip(src_hashes, recv_hashes))
        if all_match:
            ok("All 3 photos transferred and verified")
            self.passed += 1
        else:
            for i, (s, r) in enumerate(zip(src_hashes, recv_hashes)):
                status = "✓" if s == r else "✗"
                print(f"    Photo {i+1}: {status}  sent={s}  recv={r}")
            self.failed += 1


    # ============================================================
    #  TEST 10: Progress bar edge cases
    #
    #  The progress printer must not crash when given unusual
    #  values like 0% complete, 100% complete, or a 1-byte file.
    # ============================================================
    def test_progress_edge_cases(self):
        print(f"\n{BOLD}[10] Progress bar — edge cases (0%, 50%, 100%, 1-byte file){RESET}")
        from pi_sender       import _show_progress as send_progress
        from laptop_receiver import _show_progress as recv_progress

        # (bytes_done, bytes_total)
        edge_cases = [(0, 100), (50, 100), (100, 100), (1, 1), (65536, 65536)]

        try:
            for done, total in edge_cases:
                send_progress(done, total)
                recv_progress(done, total)
            print()   # end the last progress line
            ok("No crashes on any edge case")
            self.passed += 1
        except Exception as e:
            fail(f"Progress bar crashed: {e}")
            self.failed += 1


    # ============================================================
    #  SHARED HELPER: runs a transfer test and checks the MD5
    # ============================================================
    def _image_transfer_test(self, label, width, height, port):
        with tempfile.TemporaryDirectory() as tmpdir:
            src = os.path.join(tmpdir, f"{label}.jpg")
            dst = os.path.join(tmpdir, "received")
            os.makedirs(dst)
            make_test_image(src, width=width, height=height)

            src_md5 = md5_of_file(src)
            info(f"Source: {os.path.getsize(src):,} bytes  MD5={src_md5}")

            saved, err = run_loopback_transfer(src, dst, port)
            self._check_md5(saved, err, src_md5)

    def _check_md5(self, saved, err, expected_md5):
        """Verify the saved file exists and its MD5 matches the source."""
        if err:
            fail(f"Transfer error: {err}")
            self.failed += 1
            return
        if not saved or not os.path.exists(saved):
            fail("File was not saved (receive_file returned None)")
            self.failed += 1
            return

        received_md5 = md5_of_file(saved)
        info(f"Recvd : {os.path.getsize(saved):,} bytes  MD5={received_md5}")

        if expected_md5 == received_md5:
            ok("MD5 matches — file arrived without corruption")
            self.passed += 1
        else:
            fail("MD5 mismatch — file was corrupted!")
            self.failed += 1


# ================================================================
#  RUN THE TESTS
# ================================================================
if __name__ == "__main__":
    runner  = TestRunner()
    success = runner.run_all()

    # Exit with code 0 (all passed) or 1 (some failed).
    # This lets CI tools like GitHub Actions know if tests passed.
    sys.exit(0 if success else 1)
