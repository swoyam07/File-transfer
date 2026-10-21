# Setup Guide: Sender and Receiver

This guide sets up two computers to send photos and videos from one to the other over a cable or local network.

- **Sender**: the computer that has the files.
- **Receiver**: the computer that should get the files.

Every file is checked on both computers. A file only reaches the receiver if it really is an allowed image or video and contains nothing hidden. Photo and video metadata (GPS location, camera details and so on) is removed along the way.

Allowed files:

| Images | Videos |
| --- | --- |
| `.jpg` `.jpeg` `.png` `.heic` | `.mp4` `.mov` `.mkv` `.avi` |

Everything else is skipped.

---

## Part 1: Steps for both computers

Do these steps on the sender **and** on the receiver.

### Step 1. Install Python 3.12 or newer

**Windows**
1. Download Python from https://www.python.org/downloads/
2. During installation, tick **"Add Python to PATH"**.
3. Open *Command Prompt* and check:
   ```cmd
   py --version
   ```

**Linux**
```bash
python3 --version          # must show 3.12 or newer
# Arch:   sudo pacman -S python
# Ubuntu: sudo apt install python3 python3-venv
```

### Step 2. Copy the project folder

Copy the whole `File-transfer` folder to each computer, for example:

- Windows: `C:\SafeMediaTransfer\File-transfer`
- Linux: `~/Documents/File-transfer`

Both computers must run **the same version** of the project. An older copy cannot talk to the new one.

### Step 3. Create the virtual environment and install packages

Open a terminal **inside the project folder**.

**Windows (Command Prompt)**
```cmd
py -3.12 -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

**Linux**
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### Step 4. Choose a pairing code

Pick one secret code, **at least 8 characters**, for example `blue-river-2026`. Both computers must use exactly the same code. Without it, the computers refuse to connect to each other.

Don't use a code you use anywhere else.

### Step 5. Connect the computers

**Option A: direct Ethernet cable (most secure)**

Give each computer a fixed address on the cable's network adapter:

| | IP address | Subnet mask |
| --- | --- | --- |
| Sender | `192.168.50.1` | `255.255.255.0` |
| Receiver | `192.168.50.2` | `255.255.255.0` |

Leave the gateway and DNS empty.

- **Windows:** *Settings → Network & Internet → Ethernet → IP assignment → Edit → Manual → IPv4 on*, then enter the address and mask.
- **Linux:** find the cable adapter's name with `nmcli device` (for example `enp3s0`), then run:
  ```bash
  sudo nmcli con add type ethernet ifname enp3s0 con-name transfer ipv4.method manual ipv4.addresses 192.168.50.2/24
  sudo nmcli con up transfer
  ```
  Use `192.168.50.1/24` on the sender and `192.168.50.2/24` on the receiver.

**Option B: same home network (Wi‑Fi or router)**

Nothing to set up. Find the receiver's address in Step R3.

**Test the connection** from the sender:
```bash
ping 192.168.50.2
```

---

## Part 2: Receiver setup

### Step R1. Edit `config.toml` on the receiver

Open `config.toml` in a text editor and set:

```toml
[app]
mode = "receiver"

[network]
bind_ip = "192.168.50.2"     # the receiver's own LAN IP address
port = 5001

[storage]
default_destination = "~/SafeMediaInbox"      # Linux
# default_destination = "D:\\SafeMediaInbox"  # Windows (use double backslashes)

[security]
pairing_code = "blue-river-2026"   # or leave "" and type it in the window
```

`bind_ip` decides who can reach the receiver:
- `127.0.0.1` means this computer only (for testing).
- The receiver's LAN IP, e.g. `192.168.50.2`, means computers on that network.

Even on the LAN, only private network addresses are let in. That list is `allowed_sender_networks` in `[security]`.

### Step R2. Allow the port through the firewall

The receiver must accept incoming connections on port 5001.

**Windows** (Command Prompt **as Administrator**):
```cmd
netsh advfirewall firewall add rule name="Safe Media Transfer" dir=in action=allow protocol=TCP localport=5001 remoteip=192.168.50.0/24
```

**Linux** (only if a firewall is running):
```bash
# ufw
sudo ufw allow from 192.168.50.0/24 to any port 5001 proto tcp
# firewalld
sudo firewall-cmd --add-rich-rule='rule family=ipv4 source address=192.168.50.0/24 port port=5001 protocol=tcp accept'
```

If you use a home network instead of a cable, replace `192.168.50.0/24` with your network, e.g. `192.168.1.0/24`.

### Step R3. Find the receiver's IP address (Option B only)

- **Windows:** `ipconfig`, then look for *IPv4 Address*.
- **Linux:** `ip -4 addr`, then look for the `inet` line of your network adapter.

Write it down. The sender needs it.

### Step R4. Start the receiver

**Windows**
```cmd
.venv\Scripts\activate
python receiver_main.py
```
(or double-click `scripts\run_receiver.bat`)

**Linux**
```bash
source .venv/bin/activate
python receiver_main.py
```

In the window:

1. **Destination Root**: the folder where received files go. Use *Browse* to change it.
2. **Bind IP**: the receiver's LAN IP (filled in from the config).
3. **Port**: `5001`.
4. **Pairing Code**: your code.
5. Click **Start Listener**. The status changes to **Listening**.

Leave this window open while the sender works.

---

## Part 3: Sender setup

### Step S1. Install ffmpeg (removes video metadata)

ffmpeg removes location, device and title information from videos without changing the picture or sound.

**Windows**
1. Download a build from https://www.gyan.dev/ffmpeg/builds/ (the *release essentials* zip).
2. Unzip it, e.g. to `C:\ffmpeg`.
3. Add `C:\ffmpeg\bin` to *PATH*: *Start → "Edit the system environment variables" → Environment Variables → Path → New*.
4. Open a **new** Command Prompt and check with `ffmpeg -version`.

**Linux**
```bash
sudo pacman -S ffmpeg        # Arch
sudo apt install ffmpeg      # Ubuntu / Debian
```

Without ffmpeg, videos are still checked and sent, but their metadata is **not** removed. Image metadata is always removed.

### Step S2. Edit `config.toml` on the sender

```toml
[app]
mode = "sender"

[network]
receiver_ip = "192.168.50.2"   # the receiver's IP from Step R3
port = 5001                    # must match the receiver

[security]
pairing_code = "blue-river-2026"   # same code as the receiver, or leave ""

[metadata]
enabled = true
mode = "strip"
```

### Step S3. Start the sender

**Windows**
```cmd
.venv\Scripts\activate
python sender_main.py
```
(or double-click `scripts\run_sender.bat`)

**Linux**
```bash
source .venv/bin/activate
python sender_main.py
```

### Step S4. Scan and send

1. Check **Receiver IP**, **Port** and **Pairing Code**.
2. **Source Folder**: click *Browse* and pick the folder with your photos and videos. Subfolders are included.
3. Click **Scan**. Every file's real content is checked. The log shows:
   - `Blocked: ... (reason)`: files that will **not** be sent (see the table below).
   - The summary line: how many images and videos are ready.
4. Choose what to send:
   - **Transfer Images**: only images.
   - **Transfer Videos**: only videos.
   - **Transfer Both**: both.
   - **⚡ Transfer Heavy Video**: videos only, with bigger chunks. Use it for large files (1 GB+).
5. The log shows each file. At the end you see `Transfer completed: X of Y file(s) sent`, followed by any files that were not sent and why.

The receiver's log lists every file it received or rejected.

---

## Part 4: Test before real use (recommended)

Try both apps on **one** computer first:

1. Receiver window: Bind IP `127.0.0.1`, Port `5001`, a pairing code, then **Start Listener**.
2. Sender window: Receiver IP `127.0.0.1`, Port `5001`, the same pairing code.
3. Scan a folder with a few photos and send them.
4. Check that the files appear in the destination folder.

Developers can also run the automated tests:
```bash
pip install pytest pytest-timeout
pytest -q
```

---

## What the log messages mean

| Message | Meaning |
| --- | --- |
| `unrecognized_content` | The file is not really an image or video (e.g. a program renamed to `.jpg`). |
| `extension_mismatch:content_is_png` | The file was renamed to a different type (e.g. a PNG saved as `.jpg`). |
| `trailing_data_after_image` / `mp4_trailing_data` | Extra data was hidden after the end of the file. |
| `suspicious_content:...` | Script or program code was found inside the file. |
| `mkv_contains_attachments` | An MKV video has files attached inside it. |
| `blocked_extension` / `extension_not_allowed` | The file type is not allowed (`.exe`, `.zip`, `.pdf`, `.svg`, ...). |
| `metadata_removed` / `trailing_data_removed` | Information only. The extra data was cleaned off before sending. |
| `duplicate_exists` | A file with the same name is already on the receiver (see `duplicate_policy` in the config). |
| `wrong pairing code` | The two computers use different pairing codes. |
| `not an allowed LAN address` | The sender is not on an allowed local network. |
| `too many wrong pairing codes` | 5 wrong attempts; the receiver blocks that address for 5 minutes. |

---

## Troubleshooting

| Problem | Fix |
| --- | --- |
| `Connection refused` / timeout | Is the receiver listening? Are the IP and port right? Does `ping` work? Is the firewall rule in place (Step R2)? |
| `Pairing code rejected by receiver` | Type the same code on both computers. Codes are case-sensitive. |
| `receiver_protocol_version_mismatch` | One computer runs an old copy. Copy the same project version to both. |
| `is not on the local network` | The receiver IP is a public internet address. Use the LAN address. |
| `Address already in use` on the receiver | Another program, or a second receiver window, is using port 5001. Close it or choose another port on both sides. |
| `not_enough_disk_space` | Free up space on the receiver, or pick a destination on a bigger drive. |
| Videos still contain metadata | ffmpeg is not installed or not on PATH on the **sender** (Step S1). |
| Config error at start-up | The error names the bad setting. Compare it with `config.example.toml`. |

---

## Good habits

- Use a **direct cable** for the safest setup. Nothing else can reach the receiver.
- Click **Stop Listener** on the receiver when you're done.
- Keep the receiving computer's operating system and media players up to date.
- Keep the pairing code private. If you store it in `config.toml`, don't share or commit that file.
