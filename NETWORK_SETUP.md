# Network Setup and Debug Guide (Direct Cable, Linux)

This guide connects the **Sender** PC and the **Receiver** PC with one Ethernet cable and gets
them pinging each other. It then lists every error seen during real setups and how to fix each one.

Example addresses used throughout:

| PC | Role | Interface (example) | Cable IP |
|---|---|---|---|
| Laptop (`fedora`) | **Receiver** | `enp0s13f0u2u3` (USB Ethernet adapter) | `192.168.50.1/24` |
| Desktop (`dark`) | **Sender** | `enp3s0` | `192.168.50.2/24` |

Rules that prevent most problems:
- Each PC needs its **own** address in the same `192.168.50.x` range. Never give both PCs the same address.
- Do not use the Wi-Fi range (for example `192.168.0.x`) on the cable.
- `ipv4.never-default yes` keeps Wi-Fi and internet working while the cable is in use.

---

## 1. Receiver setup (do this first)

```bash
# 1. Find the wired interface and its connection name
ip -br addr
nmcli connection show            # look for TYPE "ethernet", e.g. "Wired connection 1"

# 2. Give the cable a fixed address
sudo nmcli connection modify "Wired connection 1" \
  ipv4.method manual \
  ipv4.addresses 192.168.50.1/24 \
  ipv4.never-default yes
sudo nmcli connection up "Wired connection 1"

# 3. Check it
ip -br addr                      # the wired interface must show 192.168.50.1/24 and UP

# 4. Open the app's port in the Fedora firewall
sudo firewall-cmd --add-port=5001/tcp                 # until reboot
sudo firewall-cmd --permanent --add-port=5001/tcp     # keep it after reboot
```

In the Receiver app:
- **Bind IP**: `192.168.50.1` (must be an address this PC really has, see step 3)
- **Port**: `5001`
- **Destination Root**: a folder you can write to (for example `/home/<you>/Pictures` or a mounted drive)
- **Pairing Code**: same code as the sender, at least 12 characters
- Click **Start Listener**. Status should say **Listening**.

## 2. Sender setup

```bash
ip -br addr
nmcli connection show

sudo nmcli connection modify "Wired connection 1" \
  ipv4.method manual \
  ipv4.addresses 192.168.50.2/24 \
  ipv4.never-default yes
sudo nmcli connection up "Wired connection 1"

ip -br addr                      # must show 192.168.50.2/24, NOT .1
```

## 3. Ping test (both directions)

```bash
# On the sender
ping -c 4 192.168.50.1

# On the receiver
ping -c 4 192.168.50.2
```

Good result: `4 packets transmitted, 4 received, 0% packet loss`.
If you get anything else, go to section 5.

Then test the app port from the sender:

```bash
nc -zv 192.168.50.1 5001         # "succeeded" / "Connected" = receiver is listening and reachable
```

## 4. Sending

In the Sender app:
- **Receiver IP**: `192.168.50.1`, **Port**: `5001`, same **Pairing Code**
- **Source Folder**: pick a normal folder, for example `/run/media/<you>/New Volume/Data/Motivation`,
  not the root of a drive (see error E8)
- **Scan**, then **Transfer Videos** / **Images** / **Audio** / **PDFs** / **All**

The receiver log should show `Sender 192.168.50.2 authenticated` → `Received ...` → `Transfer complete: N received, 0 rejected`.

---

## 5. Debug: errors and fixes

### E1. `Error: invalid property 'never-defult'` / `nmcli connect modify`
**Seen on:** sender. **Cause:** typos. **Fix:** the command is `nmcli connection modify` and the property is `ipv4.never-default`:
```bash
sudo nmcli connection modify "Wired connection 1" ipv4.method manual \
  ipv4.addresses 192.168.50.2/24 ipv4.never-default yes
```
Watch line continuations: each `\` must be the **last** character on the line. A space after it breaks the command.

### E2. `IP address 192.168.50.1 cannot be configured because it is already in use by host 00:E0:4C:95:1F:49` → `Activation: failed ... ip-config-unavailable`
**Seen on:** sender (`journalctl` / NetworkManager log). **Cause:** the sender was given `192.168.50.1`, which the receiver already has.
NetworkManager detects the duplicate and refuses to bring the cable up, so the interface ends up with no address and ping fails.
**Fix:** give the sender a different address (`192.168.50.2`), then `sudo nmcli connection up "Wired connection 1"`.
Check with `ip -br addr` that the sender shows `.2` and the receiver shows `.1`.

### E3. `From 192.168.50.1 icmp_seq=1 Destination Host Unreachable` / `ping: sendmsg: No route to host`
**Seen on:** receiver pinging `192.168.50.2`. **Cause:** the receiver's own cable is fine, but nothing answers at `.2`. Usually:
- the sender's cable connection is not up or failed to activate (see E2): run `ip -br addr` on the sender,
- the sender has a different address than you are pinging (for example `.3`),
- the cable or adapter has no link: `ip link show <iface>` must say `state UP`, and `cat /sys/class/net/<iface>/carrier` must print `1`.

**Fix:** fix the sender's address, then ping the address the sender actually shows.

### E4. `100% packet loss` with **no** "Unreachable" errors
**Cause:** the other PC answers ARP (it exists) but drops ping, or the reply goes out the wrong interface. Check:
- Firewall on the other PC: `sudo firewall-cmd --list-all` (Fedora allows ping by default; a custom zone may not).
- Both PCs on the **same** subnet: `/24` on both, both `192.168.50.x`.
- After changing an address, re-activate on **both** sides (`nmcli connection up ...`) so old ARP entries are cleared:
  `ip neigh flush dev <iface>`.
- The address is not also on Wi-Fi or a second adapter: `ip -br addr` must show `192.168.50.x` on only one interface.

### E5. `ping` works, but the sender cannot connect / "Connection refused" / timeout
- Receiver is not listening: click **Start Listener**, status must say **Listening**.
- Port blocked by firewall on the receiver: `sudo firewall-cmd --add-port=5001/tcp`.
- Wrong port or IP on the sender: it must match the receiver's Bind IP and Port.
- Test with `nc -zv 192.168.50.1 5001` from the sender.

### E6. Receiver log: `Refused connection from <ip>: not an allowed LAN address`
The sender's IP is outside `allowed_sender_networks` in the receiver's `config.toml`. `192.168.50.x` is allowed by default
(`192.168.0.0/16`). If you narrowed it, add the sender's address, for example `"192.168.50.2/32"`.

### E7. Receiver: `Refused ... too many wrong pairing codes` / authentication failed
The pairing codes differ. Type the same code (12+ characters) on both PCs, wait for the lockout to pass or restart the receiver.

### E8. Scan log: `Could not move ... to the rejected folder: [Errno 13] Permission denied: '/run/media/<you>/New Volume_rejected'`
**Cause:** the source folder was the root of a drive (`/run/media/<you>/New Volume`). The default rejected folder is created
**next to** the source folder, which is `/run/media/<you>/`, and only root can write there.
The scan also walked into `.Trash-1000` and `$RECYCLE.BIN` on that drive.
**Fix (any one):**
- Pick a subfolder as the source, for example `/run/media/<you>/New Volume/Data`. The rejected folder then becomes `.../New Volume/Data_rejected`.
- Or set a writable folder in `config.toml`:
  ```toml
  [storage]
  rejected_folder = "/run/media/<you>/New Volume/rejected"
  ```
- Or turn moving off: `move_rejected_files = false`.

Note: with the current version only files whose extension is **not** in `allowed_extensions` are moved. Broken `.jpg`/`.mp4`
files are skipped and left in place.

### E9. Receiver terminal: `raise ValueError("Resume state is not in progress")`
This message comes from an **older copy** of the app (`~/Downloads/File-transfer-main`). It is not in the current code.
**Fix:** run the same, current version on **both** PCs, and delete leftover `*.part` / `*.part.json` files in the destination
folder before retrying.

### E10. Receiver: cannot bind / listener does not start
The **Bind IP** is not an address this PC has. Check `ip -br addr`. The cable connection must be up before clicking
**Start Listener**. If unsure, use `0.0.0.0` (all interfaces; `allowed_sender_networks` still limits who can connect).

### E11. Files rejected or not written on the receiver
- Destination Root not writable (for example a drive mounted read-only or owned by root): `touch "<dest>/test" && rm "<dest>/test"`.
- Not enough free space on the destination drive.
- Check the receiver log for the reason after `Rejected <file>:`.

---

## 6. Quick checklist

| Check | Sender (`192.168.50.2`) | Receiver (`192.168.50.1`) |
|---|---|---|
| Cable link up | `ip link` → `state UP` | `ip link` → `state UP` |
| Correct address | `ip -br addr` shows `.2/24` | `ip -br addr` shows `.1/24` |
| Ping the other PC | `ping -c 4 192.168.50.1` | `ping -c 4 192.168.50.2` |
| Port reachable | `nc -zv 192.168.50.1 5001` | firewall allows `5001/tcp` |
| App | Receiver IP `.1`, port `5001` | Bind IP `.1`, **Listening** |
| Same pairing code | ✔ | ✔ |
| Same app version | ✔ | ✔ |

## 7. Undo the cable setup

```bash
sudo nmcli connection modify "Wired connection 1" ipv4.method auto ipv4.addresses "" ipv4.never-default no
sudo nmcli connection up "Wired connection 1"
sudo firewall-cmd --permanent --remove-port=5001/tcp   # receiver only
```
