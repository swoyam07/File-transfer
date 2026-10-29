# Receiver Setup

Set up the computer that **gets** the files (the one with the empty drive). Do this **before** the sender.

```
   SENDER PC                                   RECEIVER PC  (this one)
 ┌───────────────┐    Ethernet cable 1 Gbps   ┌──────────────────────┐
 │ 192.168.50.73 │ ────────────────────────▶  │ 192.168.50.2         │
 │ source drive  │                            │ listens on port 5001 │
 └───────────────┘                            │ saves to empty drive │
                                              └──────────────────────┘
```

Values used in this guide (change them if yours differ):

| What | Value |
| --- | --- |
| This computer's IP | `192.168.50.2` |
| Sender's IP | `192.168.50.73` |
| Port | `5001` |
| Pairing code | `blue-river-tiger-2026` (make your own, 12+ characters) |
| Where files are saved | a folder on the empty 1 TB drive |

---

## Step 1. Install Python and the app

Full instructions and fixes for common errors: [INSTALL.md](INSTALL.md).

**Fedora**
```bash
sudo dnf install python3
cd ~/Documents/File-transfer
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**Windows 11** (install Python 3.12+ from https://www.python.org/downloads/ and tick **"Add Python to PATH"**)
```cmd
cd C:\SafeMediaTransfer\File-transfer
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Use the **same version** of the project folder on both computers.

## Step 2. Give the cable a fixed IP address

| Setting | Value |
| --- | --- |
| IP address | `192.168.50.2` |
| Subnet mask | `255.255.255.0` (prefix `/24`) |
| Gateway | *(empty)* |
| DNS | *(empty)* |

**Fedora:** find the cable's adapter name with `nmcli device` (for example `enp3s0`), then:
```bash
sudo nmcli con add type ethernet ifname enp3s0 con-name transfer ipv4.method manual ipv4.addresses 192.168.50.2/24
sudo nmcli con up transfer
```

**Windows 11:** *Settings → Network & internet → Ethernet → IP assignment → Edit → Manual → IPv4 On.* Enter the IP and subnet mask, leave the gateway and DNS empty, then save.

**Check the link speed shows 1 Gbps:** `ethtool enp3s0` on Fedora; *Settings → Network & internet → Ethernet* ("Link speed") on Windows.

**Using your home network (Wi-Fi or router) instead of a cable?** Skip the fixed IP. Find this computer's address with `ip -4 addr` on Linux (the `inet` line of your adapter) or `ipconfig` on Windows (*IPv4 Address*), for example `192.168.1.20`. Use it as **Bind IP**, and give it to the sender as **Receiver IP**. A direct cable is safer, because nothing else can reach the receiver.

## Step 3. Open port 5001 in the firewall

**Fedora:** Fedora Workstation usually allows this port already. If the sender can't connect:
```bash
sudo firewall-cmd --permanent --add-rich-rule='rule family=ipv4 source address=192.168.50.0/24 port port=5001 protocol=tcp accept'
sudo firewall-cmd --reload
```

**Ubuntu (ufw):** `sudo ufw allow from 192.168.50.0/24 to any port 5001 proto tcp`

**Windows 11:** open *Command Prompt as Administrator*:
```cmd
netsh advfirewall firewall add rule name="Safe Media Transfer" dir=in action=allow protocol=TCP localport=5001 remoteip=192.168.50.0/24
```

This only lets in devices on the cable's network, not the internet. On a home network, replace `192.168.50.0/24` with yours, e.g. `192.168.1.0/24`.

## Step 4. Prepare the destination folder

Create a folder on the empty drive. It needs more free space than you are sending (800 GB fits on a 1 TB drive).

| OS | Example folder |
| --- | --- |
| Fedora | `/run/media/<your-user>/<drive-name>/SafeMediaInbox` |
| Windows 11 | `E:\SafeMediaInbox` |

## Step 5. Start the receiver and fill in the window

```bash
python receiver_main.py
```
On Windows you can also double-click `scripts\run_receiver.bat`.

```
Safe Media Transfer                                     [ Settings ]
Receiver: every file is checked again before it is saved
┌ Listener ───────────────────────────────────────────────────────────┐
│ Destination Root  [ E:\SafeMediaInbox               ] [ Browse... ] │
│ Bind IP           [ 192.168.50.2                    ] Port [ 5001 ] │
│ Pairing Code      [ ••••••••••••••••••••                          ] │
│ [ Start Listener ]  [ Stop Listener ]                ( Listening )  │
└─────────────────────────────────────────────────────────────────────┘
┌ Log ────────────────────────────────────────────────────────────────┐
│ Sender 192.168.50.73 authenticated                                  │
│ Received Reels/clip001.mp4 (24117248 bytes)                         │
└─────────────────────────────────────────────────────────────────────┘
```

| Field | Type this | Notes |
| --- | --- | --- |
| **Destination Root** | `E:\SafeMediaInbox` or `/run/media/you/Drive/SafeMediaInbox` | Use **Browse** to pick it. Subfolders from the sender are recreated here. |
| **Bind IP** | `192.168.50.2` | This computer's own cable IP. `127.0.0.1` only works for a test on one PC. |
| **Port** | `5001` | Must match the sender. |
| **Pairing Code** | `blue-river-tiger-2026` | Exactly the same as on the sender, 12+ characters. Make up your own, and don't reuse a password you use elsewhere. |

Then click **Start Listener**. Leave the window open until the transfer is done.

## Optional: save the values in `config.toml`

Then you don't have to type them each time:

```toml
[network]
bind_ip = "192.168.50.2"
port = 5001

[transfer]
duplicate_policy = "skip_identical"   # lets an interrupted transfer continue

[storage]
default_destination = "E:\\SafeMediaInbox"   # Windows: use double backslashes
# default_destination = "/run/media/you/Drive/SafeMediaInbox"   # Fedora

[security]
pairing_code = "blue-river-tiger-2026"   # or leave "" and type it in the window
```

## Optional: test on one PC first

Before the real transfer, try both apps on **one** computer:

1. Receiver window: **Bind IP** `127.0.0.1`, **Port** `5001`, a pairing code, then **Start Listener**.
2. Sender window: **Receiver IP** `127.0.0.1`, **Port** `5001`, the same pairing code.
3. Scan a folder with a few photos and send them.
4. Check that the files appear in the destination folder.

## What the log means

| Log line | Meaning |
| --- | --- |
| `Sender 192.168.50.73 authenticated` | The pairing code matched |
| `Received <file>` | The file passed every check and is saved |
| `Rejected <file>: <reason>` | Unsafe or broken file; it was deleted, not saved |
| `Skipped <file>: already exists` | Already received earlier |
| `Refused <ip>: wrong pairing code` | Codes differ; 5 wrong tries lock that address out for 5 minutes |
| `Refused connection from <ip>: not an allowed LAN address` | Not on the local network |

## If it doesn't work

| Problem | Fix |
| --- | --- |
| Status shows **Error**: "Cannot assign requested address" (Fedora) or "requested address is not valid" (Windows) | **Bind IP** isn't this computer's IP. Check it with `ip addr` (Fedora) or `ipconfig` (Windows). |
| Sender says "connection refused" or times out | Listener not started, wrong IP/port, or the firewall (Step 3) |
| `wrong pairing code` | Retype the code on both computers; it's case-sensitive |
| `not_enough_disk_space` | Free up space on the destination drive or send fewer files |
| `Address already in use` | Another program, or a second receiver window, is using port 5001. Close it, or choose another port on both computers. |
| Config error at start-up | The message names the bad setting. Compare it with `config.example.toml`. |

## Good habits

- When finished, click **Stop Listener** and unplug the cable.
- Keep the receiving computer's operating system and media players up to date.
- Keep the pairing code private. If you save it in `config.toml`, don't share that file.
