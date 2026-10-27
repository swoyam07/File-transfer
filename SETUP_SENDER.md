# Sender Setup

Set up the computer that **has** the files. Set up the [receiver](SETUP_RECEIVER.md) first and click **Start Listener** there.

```
   SENDER PC  (this one)                       RECEIVER PC
 ┌──────────────────────┐   Ethernet 1 Gbps   ┌──────────────┐
 │ 192.168.50.1         │ ──────────────────▶ │ 192.168.50.2 │
 │ source drive (800 GB)│                     │ port 5001    │
 └──────────────────────┘                     └──────────────┘

 For each file:   check ──▶ remove metadata ──▶ send ──▶ receiver checks again
                  (the next file is prepared while the current one is sent)
```

Values used in this guide (change them if yours differ):

| What | Value |
| --- | --- |
| This computer's IP | `192.168.50.1` |
| Receiver's IP | `192.168.50.2` |
| Port | `5001` |
| Pairing code | the **same** code as on the receiver, 12+ characters |
| Source folder | the folder with your videos, photos, MP3s and PDFs |

---

## Step 1. Install Python, ffmpeg and the app

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

## Step 2. Give the cable a fixed IP address

| Setting | Value |
| --- | --- |
| IP address | `192.168.50.1` |
| Subnet mask | `255.255.255.0` (prefix `/24`) |
| Gateway | *(empty)* |
| DNS | *(empty)* |

**Fedora:** find the cable's adapter name with `nmcli device` (for example `enp3s0`), then:
```bash
sudo nmcli con add type ethernet ifname enp3s0 con-name transfer ipv4.method manual ipv4.addresses 192.168.50.1/24
sudo nmcli con up transfer
```

**Windows 11:** *Settings → Network & internet → Ethernet → IP assignment → Edit → Manual → IPv4 On.* Enter the IP and subnet mask, leave the gateway and DNS empty, then save.

**Test the cable:**
```bash
ping 192.168.50.2
```
You should see replies. Also check the link speed shows **1 Gbps**: `ethtool enp3s0` on Fedora; *Settings → Network & internet → Ethernet* ("Link speed") on Windows.

## Step 3. Start the sender and fill in the window

```bash
python sender_main.py
```

```
┌─ Safe Media Transfer - Sender ─────────────────────────────────────────────┐
│ Receiver IP     [ 192.168.50.2                                           ] │
│ Port            [ 5001                                                   ] │
│ Pairing Code    [ ••••••••••••••••••••                                   ] │
│ Source Folder   [ D:\Media                                               ] │
│ [ Browse ]  [ Scan ]                                                       │
│                                                                            │
│ ┌ Scan Summary ──────────────────────────────────────────────────────────┐ │
│ │ Images: 1200 files / 4.10 GB | Videos: 21000 files / 790.00 GB |       │ │
│ │ Audio: 300 files / 2.00 GB | PDFs: 40 files / 0.20 GB | Skipped: 12    │ │
│ └────────────────────────────────────────────────────────────────────────┘ │
│ [Transfer Images] [Transfer Videos] [Transfer Audio] [Transfer PDFs]       │
│ [Transfer All] [Settings]                                                  │
│ ───────────────────────────────────────────                                │
│ Large files (1GB+):  [ ⚡ Transfer Heavy Video ]                            │
│                                                                            │
│ Current File Progress [██████████░░░░░░]   Overall Progress [███░░░░░░░░]  │
│ Logs:  [12/22540] Reels/clip012.mp4                                        │
└────────────────────────────────────────────────────────────────────────────┘
```

| Field | Type this | Notes |
| --- | --- | --- |
| **Receiver IP** | `192.168.50.2` | The receiver's cable IP, not this computer's |
| **Port** | `5001` | Must match the receiver |
| **Pairing Code** | `blue-river-tiger-2026` | Exactly the same as on the receiver |
| **Source Folder** | `D:\Media` or `/run/media/you/Drive/Media` | Use **Browse**. Subfolders are kept on the receiver. |

## Step 4. Scan, then transfer

1. Click **Scan**. It checks every file and shows the summary. Files it won't send show in the log as `Blocked: <file> (<reason>)`.
2. Pick what to send:

| Button | Sends |
| --- | --- |
| **Transfer Images** | `.jpg .jpeg .png .heic` |
| **Transfer Videos** | `.mp4 .mov .mkv .avi` |
| **Transfer Audio** | `.mp3` |
| **Transfer PDFs** | `.pdf` (without scripts, attachments or encryption) |
| **Transfer All** | everything above. **Best for your 800 GB.** |
| **⚡ Transfer Heavy Video** | videos with bigger chunks, for a folder of long 1080p/4K movies |

3. Leave both windows open until the status says `Transfer complete: N sent, M not sent`.

**If it stops** (cable unplugged, PC restarted), click **Scan** and the same button again. Finished files are skipped and the interrupted file continues where it stopped. This needs `duplicate_policy = "skip_identical"` on the receiver.

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

## If it doesn't work

| Problem | Fix |
| --- | --- |
| `Connection refused` or timeout | Receiver not listening, wrong **Receiver IP** or port, or the receiver's firewall |
| `Pairing code rejected by receiver` | Codes differ; retype on both (case-sensitive) |
| `is not on the local network` | **Receiver IP** must be a LAN address like `192.168.50.2` |
| `not_enough_temp_space` | Set `sender_temp_folder` to a drive with more free space |
| Videos sent but metadata kept | ffmpeg not found; finish Step 1 and restart the app |
| Slow (under 50 MB/s) | Check both adapters show 1 Gbps, and the temp folder isn't on the same hard drive as the videos |
