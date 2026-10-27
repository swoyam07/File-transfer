# Installation

What you need to install to run Safe Media Transfer. Do this on **both** computers, using the **same version** of the project folder.

| Needed | Sender | Receiver | Why |
| --- | :---: | :---: | --- |
| Python 3.12 or newer | ✅ | ✅ | Runs the app |
| PySide6 (from `requirements.txt`) | ✅ | ✅ | The app window |
| ffmpeg | ✅ | – | Removes video metadata. Without it, videos are still sent, but their metadata stays. |
| pytest *(optional)* | – | – | Only to run the tests |
| PyInstaller *(optional)* | – | – | Only to build `.exe` / standalone apps |

```
Install Python ──▶ get project folder ──▶ create .venv ──▶ pip install ──▶ (sender) ffmpeg ──▶ run
```

- [Linux](#linux)
- [Windows 11](#windows-11)
- [Problems](#problems)

---

## Linux

### 1. System packages

**Fedora**
```bash
sudo dnf install python3 python3-pip xcb-util-cursor
# Sender only: full ffmpeg from RPM Fusion
sudo dnf install https://mirrors.rpmfusion.org/free/fedora/rpmfusion-free-release-$(rpm -E %fedora).noarch.rpm
sudo dnf install --allowerasing ffmpeg
```

**Ubuntu / Debian / Linux Mint**
```bash
sudo apt update
sudo apt install python3 python3-venv python3-pip libxcb-cursor0
# Sender only
sudo apt install ffmpeg
```

**Arch / Manjaro**
```bash
sudo pacman -S python xcb-util-cursor
# Sender only
sudo pacman -S ffmpeg
```

Check the versions:
```bash
python3 --version    # must be 3.12 or newer
ffmpeg -version      # sender only
```

### 2. Get the project

```bash
git clone https://github.com/swoyam07/File-transfer.git ~/Documents/File-transfer
cd ~/Documents/File-transfer
```
Or copy the `File-transfer` folder from a USB drive.

### 3. Create the virtual environment and install

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Set up the config

```bash
cp config.example.toml config.toml
```
Then follow [SETUP_RECEIVER.md](SETUP_RECEIVER.md) or [SETUP_SENDER.md](SETUP_SENDER.md).

### 5. Run

Each time, open a terminal in the project folder:
```bash
source .venv/bin/activate
python receiver_main.py     # on the receiver
python sender_main.py       # on the sender
```

---

## Windows 11

### 1. Install Python and ffmpeg

Open **Command Prompt** or **PowerShell**:

```cmd
winget install Python.Python.3.12
:: Sender only
winget install Gyan.FFmpeg
```

Or download Python from https://www.python.org/downloads/. On the first installer screen, tick **"Add python.exe to PATH"**.

**Close and reopen** the terminal, then check:
```cmd
py --version        :: must be 3.12 or newer
ffmpeg -version     :: sender only
```

### 2. Get the project

```cmd
git clone https://github.com/swoyam07/File-transfer.git C:\SafeMediaTransfer\File-transfer
cd C:\SafeMediaTransfer\File-transfer
```
Or copy the `File-transfer` folder, for example to `C:\SafeMediaTransfer\File-transfer`. Avoid OneDrive folders (Desktop, Documents): syncing slows down and locks files.

### 3. Create the virtual environment and install

**Command Prompt**
```cmd
py -3.12 -m venv .venv
.venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
```

**PowerShell**
```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```
If PowerShell says *"running scripts is disabled"*, run this once, then try again:
```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

### 4. Set up the config

```cmd
copy config.example.toml config.toml
```
Then follow [SETUP_RECEIVER.md](SETUP_RECEIVER.md) or [SETUP_SENDER.md](SETUP_SENDER.md).

### 5. Run

Each time, open a terminal in the project folder:
```cmd
.venv\Scripts\activate.bat
python receiver_main.py     :: on the receiver
python sender_main.py       :: on the sender
```
Or double-click `scripts\run_receiver.bat` / `scripts\run_sender.bat`.

---

## Optional: tests and standalone apps

Same on both systems, with the virtual environment active:

```bash
pip install pytest pytest-timeout pyinstaller
pytest -q                     # run the tests
pyinstaller sender.spec       # builds into dist/
pyinstaller receiver.spec
```

## Problems

| Message | Fix |
| --- | --- |
| `python3: command not found` / `'py' is not recognized` | Python isn't installed or isn't on PATH. Reinstall, tick "Add to PATH", reopen the terminal. |
| `No module named PySide6` | The virtual environment isn't active. Run the activate command from step 5, then try again. |
| Linux: `Could not load the Qt platform plugin "xcb"` | Install `xcb-util-cursor` (Fedora/Arch) or `libxcb-cursor0` (Ubuntu). |
| Windows: `DLL load failed while importing QtCore` | Install the Visual C++ runtime: `winget install Microsoft.VCRedist.2015+.x64` |
| Fedora: `No match for argument: ffmpeg` | RPM Fusion isn't enabled. Run the `rpmfusion-free-release` command in Linux step 1. |
| `Pairing code must be at least 12 characters` | Use a longer pairing code, the same on both computers. |
| Log says ffmpeg not found, so video metadata is kept | Install ffmpeg (step 1), reopen the terminal, restart the sender. |
