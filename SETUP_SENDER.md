# Sender Setup

Set up the computer that **has** the files. Set up the [receiver](SETUP_RECEIVER.md) first and click **Start Listener** there.

```
   SENDER PC  (this one)                       RECEIVER PC
 ┌──────────────────────┐   Ethernet 1 Gbps   ┌──────────────┐
 │ 192.168.50.73        │ ──────────────────▶ │ 192.168.50.2 │
 │ source drive (800 GB)│                     │ port 5001    │
 └──────────────────────┘                     └──────────────┘

 For each file:   check ──▶ remove metadata ──▶ send ──▶ receiver checks again
                  (the next file is prepared while the current one is sent)
```

Values used in this guide (change them if yours differ):

| What | Value |
| --- | --- |
| This computer's IP | `192.168.50.73` |
| Receiver's IP | `192.168.50.2` |
| Port | `5001` |
| Pairing code | the **same** code as on the receiver, 12+ characters |
| Source folder | the folder with your videos, photos, MP3s and PDFs |

---

# Part 1. Prepare this computer

Do these once, before installing the app.

## Step 1. Give the cable a fixed IP address

The two PCs are joined by one Ethernet cable with no router, so each PC needs a fixed address. **Each PC needs a different address.**

| Setting | Value |
| --- | --- |
| IP address | `192.168.50.73` |
| Subnet mask | `255.255.255.0` (prefix `/24`) |
| Gateway | *(empty)* |
| DNS | *(empty)* |

### Fedora / Linux (NetworkManager)

**1. Find the cable's connection profile:**
```bash
nmcli connection show
```
```
NAME                UUID                                  TYPE      DEVICE
lo                  4a571cda-...                          loopback  lo
Wired connection 1  2804f3c1-...                          ethernet  --
```
`--` under DEVICE means the profile isn't active yet. That's normal.

**2. Give it the fixed address:**
```bash
sudo nmcli connection modify "Wired connection 1" \
  ipv4.method manual \
  ipv4.addresses 192.168.50.73/24 \
  ipv4.never-default yes
sudo nmcli connection up "Wired connection 1"
```
- `ipv4.never-default yes` stops the cable from becoming your internet route, so Wi-Fi keeps working while you transfer.
- `Error: invalid property 'never-defult'` means the name is misspelled. It is **`never-default`**.
- No `Wired connection` profile in the list? Create one instead. Find the adapter name with `nmcli device` (for example `enp3s0`), then:
  ```bash
  sudo nmcli connection add type ethernet ifname enp3s0 con-name transfer \
    ipv4.method manual ipv4.addresses 192.168.50.73/24 ipv4.never-default yes
  sudo nmcli connection up transfer
  ```

**3. Check that the address was accepted.** `.73` is chosen to be unusual, so it shouldn't clash with the receiver. If the connection still won't come up, look at NetworkManager's log (`sudo journalctl -u NetworkManager -f`, Ctrl+C to stop). A line like `IP address 192.168.50.73 cannot be configured because it is already in use in the network by host ...` means the other PC has the same number. Run the `modify` command again with a different last number (1–254) and `connection up`.

Check the address is on the adapter: `ip -4 addr show enp3s0` should list `inet 192.168.50.x/24`.

### Windows 11

*Settings → Network & internet → Ethernet → IP assignment → Edit → Manual → IPv4 On.* Enter the IP and subnet mask, leave the gateway and DNS empty, then save. If Windows reports an address conflict, pick another one as described above.

### Test the cable

```bash
ping 192.168.50.2        # the receiver's address
```
You should see replies. Also check the link speed shows **1 Gbps**: `ethtool enp3s0` on Fedora; *Settings → Network & internet → Ethernet* ("Link speed") on Windows.

**Using your home network (Wi-Fi or router) instead of a cable?** Skip this step. Use the receiver's home-network address (the receiver guide shows how to find it) as **Receiver IP**.

## Step 2. Make sure rejected files can be moved (external drives)

When **Scan** finds a broken or unsafe file, it moves it into a "rejected" folder ([details below](#files-that-fail-the-checks-are-moved-aside)). By default that folder goes **next to** the source folder. If your source folder is a whole external drive on Linux, that means `/run/media/<you>/`, where only root can create folders. The log then fills with:
```
Could not move Book/Rich Dad Poor Dad.pdf to the rejected folder:
  [Errno 13] Permission denied: '/run/media/darkdevil/New Volume_rejected'
```
Nothing breaks. Those files just stay where they are and the scan carries on, but they aren't moved aside.

**Fix:** point the rejected folder somewhere you can write. The setting is in `config.toml` in the app folder (Step 3):
```toml
[storage]
# On the same drive: the move is instant, and Scan skips this folder.
rejected_folder = "/run/media/darkdevil/New Volume/_rejected"
```
Use your own user name and drive name. You can also use a folder in your home, such as `"~/SafeMedia_rejected"`; that's slower, because files are copied off the drive. To turn moving off completely, set `move_rejected_files = false` under `[transfer]`.

If you still get *Permission denied* for a folder **inside** the drive, the drive is mounted read-only. With NTFS drives this usually means Windows was shut down with Fast Startup or hibernation. Shut it down fully from Windows, or check the mount with `mount | grep "/run/media"` (look for `ro`).

**Also empty the drive's Recycle Bin / Trash first.** Folders like `.Trash-1000/` and `$RECYCLE.BIN/` are ordinary folders to the scanner, so deleted files inside them get scanned, and sent, like any other file. Or pick a subfolder as the source instead of the whole drive.

---

# Part 2. Install and run the app

## Step 3. Install Python, ffmpeg and the app

Full instructions and fixes for common errors: [INSTALL.md](INSTALL.md).

ffmpeg removes video metadata (location, device, title) without re-encoding. Without it, videos are still checked and sent, but their metadata stays.

**Fedora** (full ffmpeg comes from RPM Fusion)
```bash
sudo dnf install https://mirrors.rpmfusion.org/free/fedora/rpmfusion-free-release-$(rpm -E %fedora).noarch.rpm
sudo dnf install --allowerasing ffmpeg python3
cd ~/Documents/File-transfer
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**Windows 11** (install Python 3.12+ from https://www.python.org/downloads/ and tick **"Add Python to PATH"**)
```cmd
winget install Gyan.FFmpeg
cd C:\SafeMediaTransfer\File-transfer
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```
Open a **new** terminal afterwards and check with `ffmpeg -version`.

## Step 4. Start the sender and fill in the window

```bash
python sender_main.py
```
On Windows you can also double-click `scripts\run_sender.bat`. To try everything on one PC first, see [the one-PC test](SETUP_RECEIVER.md#optional-test-on-one-pc-first).

```
Safe Media Transfer                                             [ Settings ]
Sender: send checked media to the receiver
┌ Connection ────────────────────────────────────────────────────────────────┐
│ Receiver IP   [ 192.168.50.2                              ]  Port [ 5001 ] │
│ Pairing Code  [ ••••••••••••••••••••                                     ] │
└────────────────────────────────────────────────────────────────────────────┘
┌ Source ────────────────────────────────────────────────────────────────────┐
│ [ D:\Media                                        ] [ Browse... ] [ Scan ] │
└────────────────────────────────────────────────────────────────────────────┘
┌ Scan Summary ──────────────────────────────────────────────────────────────┐
│ [▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓ Scan complete (100%) ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓] │
│ │     1,200      │ │    21,000     │ │      300       │ │       40       │ │
│ │ Images·4.10 GB │ │Videos·790.0 GB│ │ Audio·2.00 GB  │ │ PDFs·200.00 MB │ │
│ Skipped: 12   ·   Warnings: 3                                              │
└────────────────────────────────────────────────────────────────────────────┘
┌ Transfer ──────────────────────────────────────────────────────────────────┐
│ [Transfer Images] [Transfer Videos] [Transfer Audio] [Transfer PDFs]       │
│                                                          [ Transfer All ]  │
│ ( Transferring... ) [▓▓▓▓▓▓▓▓▓ Sent 42% (file 9,467 of 22,540) ░░░░░░░░░░] │
│ Reels/clip012.mp4  ·  67%                                                  │
└────────────────────────────────────────────────────────────────────────────┘
┌ Log ───────────────────────────────────────────────────────────────────────┐
│ [12/22540] Reels/clip012.mp4                                               │
└────────────────────────────────────────────────────────────────────────────┘
```

| Field | Type this | Notes |
| --- | --- | --- |
| **Receiver IP** | `192.168.50.2` | The receiver's cable IP, not this computer's |
| **Port** | `5001` | Must match the receiver |
| **Pairing Code** | `blue-river-tiger-2026` | Exactly the same as on the receiver |
| **Source Folder** | `D:\Media` or `/run/media/you/Drive/Media` | Use **Browse**. Subfolders are kept on the receiver. |

## Step 5. Scan, then transfer

1. Click **Scan**. It checks every file and shows the summary. Files it won't send show in the log as `Blocked: <file> (<reason>)`.
2. Pick what to send:

| Button | Sends |
| --- | --- |
| **Transfer Images** | `.jpg .jpeg .png .heic` |
| **Transfer Videos** | `.mp4 .mov .mkv .avi` |
| **Transfer Audio** | `.mp3` |
| **Transfer PDFs** | `.pdf` (without scripts, attachments or encryption) |
| **Transfer All** | everything above. **Best for your 800 GB.** |

3. Leave both windows open until the status says `Transfer complete: N sent, M not sent`.

**If it stops** (cable unplugged, PC restarted), click **Scan** and the same button again. Finished files are skipped and the interrupted file continues where it stopped. This needs `duplicate_policy = "skip_identical"` on the receiver.

## Files that fail the checks are moved aside

Files that are corrupted, in the wrong format or unsafe are **moved** (not copied, not repaired, not sent) out of your source folder into **one** folder next to it. Subfolders are kept, and `reasons.csv` says why each file was moved.

```
D:\Media\                       D:\Media_rejected\
├── Trip\                       ├── Trip\
│   ├── clip1.mp4  ✅ sent       │   ├── broken.mp4      ◀ moved here
│   ├── broken.mp4 ──────────▶  │   └── fake.jpg        ◀ moved here
│   └── fake.jpg   ──────────▶  ├── Family\
├── Family\                     │   ├── bad1.jpg        ◀ moved here
│   ├── bad1.jpg   ──────────▶  │   ├── bad2.png        ◀ moved here
│   ├── bad2.png   ──────────▶  │   └── virus.pdf       ◀ moved here
│   ├── virus.pdf  ──────────▶  └── reasons.csv
│   └── photo.jpg  ✅ sent
```

`reasons.csv` (opens in Excel or LibreOffice):

| time | original_path | reason | moved_to |
| --- | --- | --- | --- |
| 2026-10-27T10:00:00Z | `Trip/broken.mp4` | `mp4_truncated` | `Trip/broken.mp4` |
| 2026-10-27T10:00:00Z | `Trip/fake.jpg` | `extension_mismatch:content_is_png` | `Trip/fake.jpg` |
| 2026-10-27T10:05:12Z | `Family/virus.pdf` | `receiver: pdf_active_content:JavaScript` | `Family/virus.pdf` |

Files are moved when **Scan** finds a problem, and also after a transfer if the sender or receiver rejected them.

These are **not** moved, because nothing is wrong with the file itself:
- types this app doesn't send (`.txt`, `.docx`, ...)
- files damaged on the cable (`hash_mismatch`); just transfer again
- files skipped because the receiver already has them

| Setting in `config.toml` | Value |
| --- | --- |
| `[transfer] move_rejected_files` | `true` = move bad files (default in this setup), `false` = leave them in place |
| `[storage] rejected_folder` | `""` = next to the source folder (`D:\Media` → `D:\Media_rejected`), or any folder you choose |

## Optional: save the values in `config.toml`

```toml
[network]
receiver_ip = "192.168.50.2"
port = 5001

[storage]
# Where the metadata-free copy of each file is made before sending.
# Empty = automatic (/var/tmp on Fedora, %TEMP% on Windows).
# Best: a folder on the SSD, not on the drive with your videos.
# Needs free space for one copy of your largest movie.
sender_temp_folder = ""

[security]
pairing_code = "blue-river-tiger-2026"   # or leave "" and type it in the window
```

## Expected speed

With hard drives (~100 MB/s) on both sides and a 1 Gbps cable, expect **about 90–100 MB/s**, roughly **2.5–3 hours for 800 GB**. Many small reels take a little longer than a few big movies of the same total size.

## What the log means

| Log line | Meaning |
| --- | --- |
| `[12/22540] <file>` | Sending file 12 of 22540 |
| `removing video metadata: <file>` | ffmpeg is cleaning the next video |
| `rejected: sender: <reason>` | This computer found a problem and didn't send it |
| `rejected: receiver: <reason>` | The receiver refused it, e.g. `suspicious_content`, `pdf_active_content:JavaScript` |
| `skipped: duplicate_exists` | The receiver already has it |

### Common reasons a file is blocked or rejected

| Reason | Meaning |
| --- | --- |
| `unrecognized_content` | Not really a photo, video, MP3 or PDF (e.g. a program renamed to `.jpg`) |
| `extension_mismatch:content_is_png` | Renamed to a different type (e.g. a PNG saved as `.jpg`) |
| `trailing_data_after_image` / `mp4_trailing_data` | Extra data hidden after the end of the file |
| `suspicious_content:...` | Script or program code found inside the file |
| `mkv_contains_attachments` | An MKV video has files attached inside it |
| `pdf_active_content:...` | A PDF with scripts, attachments or encryption |
| `blocked_extension` / `extension_not_allowed` | A type this app never sends (`.exe`, `.zip`, `.svg`, ...) |
| `metadata_removed` / `trailing_data_removed` | Information only: the extra data is cleaned off before sending |

## If it doesn't work

| Problem | Fix |
| --- | --- |
| `Connection refused` or timeout | Receiver not listening, wrong **Receiver IP** or port, or the receiver's firewall |
| `Pairing code rejected by receiver` | Codes differ; retype on both (case-sensitive) |
| `receiver_protocol_version_mismatch` | One computer runs an older copy; put the same project version on both |
| Config error at start-up | The message names the bad setting. Compare it with `config.example.toml`. |
| `is not on the local network` | **Receiver IP** must be a LAN address like `192.168.50.2` |
| `not_enough_temp_space` | Set `sender_temp_folder` to a drive with more free space |
| Videos sent but metadata kept | ffmpeg not found; finish Step 3 and restart the app |
| `Could not move ... Permission denied: '/run/media/..._rejected'` | Set `rejected_folder` to a writable folder (Step 2) |
| `IP address ... already in use in the network by host ...` | Both PCs have the same address; give this one another (Step 1) |
| `invalid property 'never-defult'` | Typo: it is `ipv4.never-default` (Step 1) |
| Slow (under 50 MB/s) | Check both adapters show 1 Gbps, and the temp folder isn't on the same hard drive as the videos |
