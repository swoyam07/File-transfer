# Safe Media Transfer

![Python](https://img.shields.io/badge/python-3.12%2B-blue)
![GUI](https://img.shields.io/badge/GUI-PySide6-41cd52)
![Platforms](https://img.shields.io/badge/platform-Windows%20%7C%20Linux-lightgrey)

Offline desktop tool that moves **approved photos, videos, MP3s and PDFs** from one PC to another over a direct LAN or Ethernet connection. It needs no cloud, server, database or browser. You run two apps, **Sender** and **Receiver**. Every file is checked on both sides, so a modified sender cannot get anything past the receiver.

## Contents

- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
- [Usage](#usage)
- [Security model](#security-model)
- [Testing](#testing)
- [Building executables](#building-executables)
- [Project structure](#project-structure)
- [Further docs](#further-docs)

## Features

- Separate PySide6 **Sender** and **Receiver** desktop apps
- Direct TCP transfer with mutual pairing-code authentication
- Real content validation for JPEG, PNG, HEIC, MP4/MOV, MKV, AVI, MP3 and PDF. Renamed or polyglot files are rejected
- PDFs with JavaScript, embedded files, launch actions or encryption are rejected
- Removes metadata (EXIF, GPS, XMP, video tags, MP3 tags) before sending
- SHA-256 per file, signed with a per-session key
- Resumable transfers (`.part` + `.part.json`)
- Human-readable TOML config and plain log files

## Requirements

| | |
| --- | --- |
| OS | Windows 10/11 or Linux |
| Python | 3.12 or newer |
| Network | Direct Ethernet / LAN, or `localhost` for testing |
| Optional | [`ffmpeg`](https://ffmpeg.org/) on the sender, to strip video metadata |

## Installation

```bash
git clone https://github.com/swoyam07/File-transfer.git
cd File-transfer
```

<details open>
<summary><b>Linux / macOS</b></summary>

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# optional, for video metadata removal
sudo apt install ffmpeg      # or: sudo pacman -S ffmpeg
```
</details>

<details>
<summary><b>Windows (PowerShell)</b></summary>

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```
</details>

### Configuration

Copy the example config and set the same `pairing_code` on both computers. You can also type the code into the app window.

```bash
cp config.example.toml config.toml
```

If `config.toml` is missing, the apps use `config.example.toml`. Logs are written to `logs/`.

## Usage

Start the **receiver** first, then the **sender**:

```bash
python receiver_main.py
python sender_main.py
```

On Windows you can use `scripts\run_receiver.bat` and `scripts\run_sender.bat` instead.

### Quick localhost test

1. Run `receiver_main.py`, choose a destination folder, and start listening on `127.0.0.1:5001`.
2. Run `sender_main.py` and choose a source folder.
3. Click **Scan**, review the file list, then **Transfer**.

### Fastest setup for a big transfer

With hard drives on both PCs (~100 MB/s) and a 1 Gbps cable (~115 MB/s), the drives are the limit. Expect about **100 MB/s, or 2.5–3 hours for 800 GB**, if:

1. **Both network cards show 1.0 Gbps.** Windows: Settings → Network → Ethernet → Link speed. Fedora: `ethtool <interface>`.
2. **ffmpeg is installed on the sender**: from RPM Fusion on Fedora, or `winget install Gyan.FFmpeg` on Windows. See [SETUP_SENDER.md](SETUP_SENDER.md).
3. **The sender's temp folder is on a different drive than the videos**, ideally the SSD with the operating system. The default (`/var/tmp` on Fedora, `%TEMP%` on Windows) usually is. If not, set `sender_temp_folder` in `config.toml`. It needs free space for one copy of the largest movie.
4. **The receiver's port is open in its firewall:**
   - Fedora: `sudo firewall-cmd --add-port=5001/tcp`. This lasts until reboot.
   - Windows: allow the app when Windows asks, or add an inbound rule for TCP port 5001.
5. Use **Transfer All** for everything at once, or **Transfer Heavy Video** for a folder of long movies.

The sender cleans the next file while the current one is being sent, so the source drive, cable and destination drive work at the same time. If the transfer stops, run it again with the same folders. With `duplicate_policy = "skip_identical"` on the receiver, finished files are skipped and the interrupted file continues where it left off. With `replace`, everything is sent again.

## Security model

Only images (`.jpg .jpeg .png .heic`), videos (`.mp4 .mov .mkv .avi`, optionally `.m4v .webm`), audio (`.mp3`) and documents (`.pdf`) are transferred. Remove a type from `[allowed_extensions]` in `config.toml` to stop sending it. Every check runs on the sender **and again on the receiver**.

| Threat | Protection |
| --- | --- |
| Executable or script renamed to `.jpg` / `.mp4` | Real file structure is parsed; unknown content is rejected |
| Image renamed to another type (PNG → JPG) | Detected format must match the extension |
| Malware appended after an image or video (polyglot) | Data after the end of the container is rejected / removed |
| Scripts hidden inside a file (`<script>`, PHP, PowerShell, EXE stub) | Whole file is scanned; any hit rejects the file |
| Files attached inside MKV videos | Rejected (sender drops them when ffmpeg is available) |
| PDF that runs code or opens things (JavaScript, launch/submit actions, embedded files, multimedia, encryption) | Rejected, including when hidden in compressed object streams or written as `/J#61vaScript` |
| Title, artist, cover art in MP3s | ID3/APE tags removed on both sides |
| EXIF / GPS / XMP / comments in photos | Removed on both sides (rotation flag kept) |
| Author / title in PDFs | **Not removed.** Check PDFs before sending if this matters |
| Video title, location, device info, GPS tracks | Removed on the sender with ffmpeg (no re-encoding) |
| Another device on the LAN pushing files | Pairing code of 12+ characters (HMAC challenge, never sent over the wire); 5 wrong codes from one address, or 15 from all addresses together, = 5-minute lockout |
| Received file opened or run by mistake | Never executable on Linux/macOS; tagged "from another computer" (Mark of the Web) on Windows so Defender/SmartScreen check it |
| Connections from outside the LAN | Receiver accepts only private / link-local peers; sender refuses public targets |
| Data altered in transit | SHA-256 per file, signed with a per-session key |
| Path tricks (`../`, `C:`, `file.jpg:stream`, `CON`) | Rejected before anything is written |
| Huge messages / disk filling | Message size limits, per-file size limit, free-space check |

Files appear in the destination folder only after they pass every check. Rejected files are deleted and listed in the receiver log. On the sender, files that fail because they are corrupted, in the wrong format or unsafe are moved (not repaired or sent) into one `<source>_rejected` folder, with `reasons.csv` saying why. See [SETUP_SENDER.md](SETUP_SENDER.md#files-that-fail-the-checks-are-moved-aside). See [SECURITY.md](SECURITY.md) for details.

### Extra safety: check before using

This app protects the files it transfers. Connecting two PCs still opens a network path between them, so malware that is already on one PC could attack the other through Windows file sharing or other services. Before each transfer:

- [ ] Use a **direct cable** between the two PCs, not a shared office network or router if you can avoid it.
- [ ] On Windows, set the network to **Public**. That turns off network discovery and file sharing.
- [ ] **Turn off file and printer sharing**, and don't share any folders.
- [ ] Leave the **firewall ON**. Only allow the receiver's port (for example `5001`).
- [ ] Keep **Windows/Linux updated** and run an **antivirus scan** on the sender PC first.
- [ ] Don't connect either PC to the internet through the other one (no bridging or internet sharing).
- [ ] **Unplug the cable** when the transfer is done.

## Testing

```bash
pip install pytest pytest-timeout     # or: pip install -e .[dev]
pytest -q
```

The end-to-end attack tests in `tests/unit/test_media_security.py` run over localhost. The real-ffmpeg test is skipped when `ffmpeg` is not installed.

## Building executables

```bash
pyinstaller sender.spec
pyinstaller receiver.spec
```

Output goes to `dist/`. On Windows you can also use `scripts\build_sender.bat` and `scripts\build_receiver.bat`.

- Builds use `onedir` (not `onefile`), which is easier to debug and deploys PySide6 more reliably.
- Keep `config.toml` next to the executable.
- Do not disable Windows Defender, SmartScreen or firewall protections.

## Project structure

```
app/
├── config/       # config loading and validation
├── scanning/     # folder walk, extension and signature policy
├── validation/   # media inspector, content scanner, sanitizers
├── security/     # handshake/auth, network policy, path validation
├── transfer/     # sender and receiver transfer services
├── state/        # resume store (atomic JSON)
├── protocol/     # framing helpers
└── ui/           # PySide6 windows and background workers
sender_main.py    # Sender entry point
receiver_main.py  # Receiver entry point
tests/            # pytest suite
scripts/          # Windows run/build helpers
```

## Further docs

- [INSTALL.md](INSTALL.md): what to install on Linux and Windows, step by step
- [QUICKSTART.md](QUICKSTART.md): fastest way to get running
- [SETUP_SENDER.md](SETUP_SENDER.md) and [SETUP_RECEIVER.md](SETUP_RECEIVER.md): step-by-step setup for each computer, with what to type in each window
- [SETUP_GUIDE.md](SETUP_GUIDE.md) and [SETUP_SENDER_RECEIVER.md](SETUP_SENDER_RECEIVER.md): older combined setup guides
- [SECURITY.md](SECURITY.md): security design
