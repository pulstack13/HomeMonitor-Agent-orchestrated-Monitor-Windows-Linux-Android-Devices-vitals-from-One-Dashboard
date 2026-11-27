# HomeMonitor complete setup guide

This guide takes you from a blank Windows PC, Linux machine or Android phone to a working
HomeMonitor dashboard with monitoring agents. It is written for someone who has not used
HomeMonitor before. Commands are shown exactly as you should type them, with example
values that you must replace.

**Time needed:** about 20 minutes for one server and one agent; 10 more minutes per extra
device.

**What you need:**

- One device that stays on most of the time (the *server* or *controller*). A Windows PC,
  a Linux PC, an old Android phone or an Android TV box running Termux all work.
- One or more devices to monitor (*agents*): Windows, Ubuntu, Debian, Linux Mint or
  Android.
- A home Wi-Fi/Ethernet network where the devices can reach each other.
- Administrator access to the server and to each monitored PC.
- Python 3.10+ on the server and on desktop agents. Android uses Termux.

> **Security first:** HomeMonitor is for a trusted home LAN. Do not forward TCP 8787 from
> your router to the internet. Do not reuse your Wi-Fi password as the admin token. Do not
> post screenshots containing the admin token or pairing code. Read
> [Security and remote access](#10-security-and-remote-access) before changing anything.

## Contents

1. [How HomeMonitor is organised](#1-how-homemonitor-is-organised)
2. [Before you install](#2-before-you-install)
3. [Install the controller](#3-install-the-controller)
4. [Open the dashboard for the first time](#4-open-the-dashboard-for-the-first-time)
5. [Add a Windows agent](#5-add-a-windows-agent)
6. [Add an Ubuntu, Debian or Linux Mint agent](#6-add-an-ubuntu-debian-or-linux-mint-agent)
7. [Add an Android agent](#7-add-an-android-agent)
8. [Use the dashboard](#8-use-the-dashboard)
9. [Configure and maintain the system](#9-configure-and-maintain-the-system)
10. [Security and remote access](#10-security-and-remote-access)
11. [Uninstall](#11-uninstall)
12. [Troubleshooting](#12-troubleshooting)
13. [Validation status and limitations](#13-validation-status-and-limitations)
14. [Command reference](#14-command-reference)

---

## 1. How HomeMonitor is organised

```text
             +-----------------------------------------------+
             |             Controller (one device)           |
             |  dashboard + HTTP API + SQLite + discovery    |
             |  default: TCP 8787, UDP 45892                 |
             +----------------------+------------------------+
                                    |
                 +------------------+------------------+
                 |                  |                  |
        +--------v-------+  +-------v--------+  +------v---------+
        | Windows agent  |  | Linux agent    |  | Android agent  |
        | Python+psutil  |  | Python+psutil  |  | Termux, stdlib |
        +----------------+  +----------------+  +----------------+
```

- You need **one controller**, not one per device.
- Each monitored machine runs an **agent**. The agent only makes outbound HTTP requests to
  the controller; it does not accept inbound connections.
- The controller serves the dashboard to any browser on the same LAN.
- The controller stores data locally in SQLite. Nothing is sent to a cloud service.
- The optional `/lite` page and Android Lite app are read-only views. They are not
  required for monitoring.

### Naming used in this guide

| Name | Meaning | Example placeholder |
| --- | --- | --- |
| Controller IP | LAN address of the server | `192.0.2.10` |
| Controller URL | `http://` + IP + port | `http://192.0.2.10:8787` |
| Admin token | Password for the dashboard | generated, 43 characters |
| Pairing code | One-time code used to register an agent | `ABCD-1234` |
| Device name | Friendly label shown in the dashboard | `Living Room PC` |

`192.0.2.0/24` and `ABCD-1234` are documentation examples. Replace them with your real
values. Do not copy the examples literally.

---

## 2. Before you install

### 2.1 Choose the controller device

Use a device that stays powered and connected:

- A desktop PC that is usually on.
- A small Linux server, mini PC or Raspberry Pi-class machine.
- An old Android phone or Android TV box with Termux. This is the lowest-power option and
  was part of the original deployment, but Android may aggressively stop background apps;
  Termux:Boot, a wake lock and battery-optimisation exemptions are required.

The controller does not need a GPU or a database server. A dual-core 1 GHz machine with
512 MB RAM is enough for a small home network. Allow 250 MB of disk plus database growth;
the default retention settings keep a few devices to a small number of megabytes per week.

### 2.2 Find the controller's LAN address

You will use this address in every agent. It must be reachable from the other devices and
should not change.

**Windows:**

```powershell
ipconfig
```

Look for the IPv4 address of your active Wi-Fi or Ethernet adapter, for example
`192.0.2.10`.

**Ubuntu / Debian / Linux Mint:**

```bash
hostname -I
ip route
```

**Android / Termux:**

```bash
ifconfig 2>/dev/null || ip addr
```

If your router supports DHCP reservations, reserve the controller's address so it does not
change. Write the address down. Do not use `127.0.0.1` in an agent on another device:
`127.0.0.1` always means "this device".

### 2.3 Check the required ports

- TCP **8787**: dashboard, API, agents.
- UDP **45892**: optional automatic discovery.

On Windows:

```powershell
Test-NetConnection 192.0.2.10 -Port 8787
```

On Linux:

```bash
nc -vz 192.0.2.10 8787
```

On Android/Termux, `nc` is available in the `net-utils` package if needed. Port checking is
optional; the dashboard itself is the final test.

### 2.4 Install Python (desktop only)

**Windows 10/11:**

1. Open PowerShell.
2. Check whether Python is available:

   ```powershell
   py -3 --version
   ```

3. If it is missing, either run `agents\windows\Install Python (winget).cmd` or install
   Python 3.12+ from <https://www.python.org/downloads/> and tick **Add python.exe to
   PATH**.
4. Close and reopen PowerShell, then confirm:

   ```powershell
   py -3 --version
   Python 3.12.10
   ```

**Ubuntu / Debian / Linux Mint:**

```bash
python3 --version
```

If this is below 3.10, install a newer Python through your distribution's repositories or
a supported backport. The agent installer can install `python3-venv` and `python3-psutil`
with `--install-deps`, but it does not upgrade Python itself.

### 2.5 Get the HomeMonitor files

You need the repository or a release archive on the controller and on each desktop agent.
The public repository is not yet uploaded; use the directory/archive you were given.

- From a folder: open a terminal in the folder containing `README.md`.
- From a `.tar.gz`: extract it first, for example `tar -xzf HomeMonitor-1.0.0.tar.gz`.
- On Windows: right-click the ZIP, **Extract All**, and open PowerShell in the extracted
  folder.

Do not run installers directly from inside a ZIP file. Windows and Linux need real files on
disk.

---

## 3. Install the controller

Choose **one** of the options below. Do not install the controller and an agent from the
same folder at the same time unless you intend to monitor the server itself; that is
allowed, but install the server first.

### Option A - Windows 10/11 controller

This installs for the current user. It does not require administrator rights. It starts
when that user signs in, not before the first login.

1. Open PowerShell in the HomeMonitor folder.
2. Run:

   ```powershell
   .\server\windows\Install HomeMonitor Server.cmd
   ```

   You can also run the PowerShell script directly:

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File .\server\windows\install-server.ps1
   ```

3. The script checks Python, copies the server to
   `%LOCALAPPDATA%\HomeMonitor\Server`, creates a private virtual environment, starts the
   server hidden and prints the dashboard details.

Representative output:

```text
==> Checking Python
==> Installing server files
==> Creating the local Python environment
==> Installing the sign-in startup shortcut
==> Starting the server in the background

HomeMonitor server installed.
  Install   : C:\Users\YOURNAME\AppData\Local\HomeMonitor\Server
  Data      : C:\Users\YOURNAME\AppData\Local\HomeMonitor\ServerData
  Dashboard : http://127.0.0.1:8787/
  LAN URL   : http://<this-pc-lan-ip>:8787/
  Admin     : <generated admin token>
  Pair code : ABCD-1234
  Log       : C:\Users\YOURNAME\AppData\Local\HomeMonitor\ServerData\controller.log
```

Values will differ. The token and code are also saved in the data directory.

4. If Windows Firewall asks whether to allow Python, choose **Private networks** only.
   If no prompt appears and other devices cannot connect, add a rule from an administrator
   PowerShell:

   ```powershell
   New-NetFirewallRule -DisplayName "HomeMonitor (Private)" `
     -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8787 -Profile Private
   ```

   Change `8787` if you installed on another port.

5. Verify locally:

   ```powershell
   Invoke-RestMethod http://127.0.0.1:8787/healthz
   ```

   Expected:

   ```text
   service  version schema      time
   -------  ------- ------      ----
   homemonitor 1.0.0      1 1795752390.0
   ```

6. Find the LAN URL:

   ```powershell
   ipconfig
   ```

   Open `http://YOUR-LAN-IP:8787/` on another device. If it does not load, see
   [Troubleshooting](#12-troubleshooting).

7. Useful locations and controls:

   | Item | Location/command |
   | --- | --- |
   | Install directory | `%LOCALAPPDATA%\HomeMonitor\Server` |
   | Data directory | `%LOCALAPPDATA%\HomeMonitor\ServerData` |
   | Admin token | `...\ServerData\config.json`, field `admin_token` |
   | Pairing code | `...\ServerData\pairing_code.txt` |
   | Log | `...\ServerData\controller.log` |
   | Open console | Start menu -> **HomeMonitor Server Console** |
   | Stop | Close the hidden `pythonw.exe`, or run the uninstaller |
   | Dashboard shortcut | Start menu -> **HomeMonitor Dashboard** |

8. Read the token without opening the dashboard:

   ```powershell
   (Get-Content "$env:LOCALAPPDATA\HomeMonitor\ServerData\config.json" -Raw |
     ConvertFrom-Json).admin_token
   ```

To change the port or bind address later, re-run the installer with `-Port` and `-Bind`.
It keeps the existing database and credentials.

### Option B - Ubuntu, Debian or Linux Mint controller

This installs a systemd service that starts at boot. It requires `sudo`.

1. Open a terminal in the extracted HomeMonitor folder.
2. Install Python and the virtual-environment support if they are missing:

   ```bash
   sudo apt update
   sudo apt install -y python3 python3-venv
   ```

3. Run the installer:

   ```bash
   sudo bash server/install-linux.sh
   ```

   To use a different port:

   ```bash
   sudo bash server/install-linux.sh --port 8787
   ```

   The installer checks for systemd, Python 3.10+, `server/`, `common/` and `dashboard/`.
   It creates the system user `homemonitor`, installs to `/opt/homemonitor`, stores data in
   `/var/lib/homemonitor`, and writes `/etc/homemonitor/server.env`.

Representative output:

```text
HomeMonitor server installer
  Distribution : Ubuntu 24.04.1 LTS
  Source       : /home/you/HomeMonitor
  Install dir  : /opt/homemonitor
  Data dir     : /var/lib/homemonitor
  Listen       : 0.0.0.0:8787
Creating system user homemonitor...
...
HomeMonitor server is running.

  Dashboard : http://0.0.0.0:8787/
              http://192.0.2.10:8787/
  Admin token: <generated admin token>
  Pair code  : ABCD-1234
  Data       : /var/lib/homemonitor
  Config     : /etc/homemonitor/server.env
  Logs       : sudo journalctl -u homemonitor-controller -f
```

4. Verify:

   ```bash
   curl http://127.0.0.1:8787/healthz
   ```

   Expected JSON:

   ```json
   {"service":"homemonitor","version":"1.0.0","schema":1,"time":1795752390.0}
   ```

5. Check the service:

   ```bash
   systemctl status homemonitor-controller --no-pager
   ```

   Expected: `active (running)`.

6. Read the credentials:

   ```bash
   sudo python3 -c "import json; print(json.load(open('/var/lib/homemonitor/config.json'))['admin_token'])"
   sudo cat /var/lib/homemonitor/pairing_code.txt
   ```

7. Allow TCP 8787 from your LAN if a firewall is active. With UFW, replace
   `YOUR_LAN_CIDR` with your network prefix. For a typical home LAN this is the first
   three octets of the controller address followed by `0/24` (for example the controller
   at `x.y.z.10` implies `x.y.z.0/24`):

   ```bash
   sudo ufw allow from YOUR_LAN_CIDR to any port 8787 proto tcp
   sudo ufw status
   ```

   Do not allow the port from `Anywhere` on an untrusted network.

8. Change configuration later:

   ```bash
   sudo nano /etc/homemonitor/server.env
   sudo systemctl restart homemonitor-controller
   ```

9. Logs:

   ```bash
   sudo journalctl -u homemonitor-controller -f
   sudo tail -f /var/lib/homemonitor/controller.log
   ```

### Option C - Android/Termux controller

This is the lowest-power option. It requires Termux and Termux:Boot from **F-Droid**, not
the old Play Store build.

1. Install **Termux** and **Termux:Boot** from F-Droid.
2. Open Termux:Boot once, then close it. This registers the boot receiver.
3. Open Android Settings -> Apps -> Termux -> Battery -> **Unrestricted** (wording varies).
   Also disable "Put unused apps to sleep" for Termux if your vendor has it.
4. In Termux, update packages and install Python:

   ```bash
   pkg update -y
   pkg upgrade -y
   pkg install -y python
   python --version
   ```

5. Get the HomeMonitor files into Termux. If you copied an archive to the phone's Download
   folder:

   ```bash
   termux-setup-storage
   cd ~
   tar -xzf ~/storage/downloads/HomeMonitor-1.0.0.tar.gz
   cd HomeMonitor-1.0.0
   ```

   If the files are already in Termux, `cd` to the folder containing `README.md`.

6. Prepare the controller:

   ```bash
   bash server/termux/setup.sh
   ```

   Representative output:

   ```text
   HomeMonitor controller is prepared.

     Project : /data/data/com.termux/files/home/HomeMonitor-1.0.0
     Data    : /data/data/com.termux/files/home/.local/share/homemonitor
     Boot    : /data/data/com.termux/files/home/.termux/boot/homemonitor-controller.sh
     Log     : /data/data/com.termux/files/home/homemonitor-controller.log
   ```

7. Start it in the foreground the first time:

   ```bash
   bash server/termux/start.sh
   ```

   You should see the same startup banner as the desktop controller, including a LAN URL
   such as `http://192.0.2.10:8787/`, the admin token and the pairing code.

8. Keep Termux running and acquire a wake lock. The start script requests one
   automatically. If you use the boot script, it also requests one.

9. Open the dashboard from another device on the same Wi-Fi. If it does not load, check
   that the phone and the browser are on the same network and that "AP isolation" or
   "client isolation" is disabled on the router.

10. Test the boot script without rebooting:

    ```bash
    sh ~/.termux/boot/homemonitor-controller.sh &
    ```

    Then reboot the phone and wait up to two minutes. Check:

    ```bash
    tail -f ~/homemonitor-controller.log
    ```

11. Credentials are in
    `~/.local/share/homemonitor/config.json` and `pairing_code.txt`.

Termux notes:

- A phone may kill background processes despite Termux:Boot. Keep it on mains power,
  disable battery optimisation and verify after a reboot.
- Android 13+ restricts `/proc` for apps, but the controller itself only needs its own
  process, SQLite and the network. The Android **agent** has more limitations; see
  [section 7](#7-add-an-android-agent).
- Do not run the controller on a phone that is also expected to sleep deeply for days.

### Option D - Run from source without installing (development)

From the repository root:

```bash
python -m server --data-dir ./data-dev --port 8788 --no-discovery
```

On Windows, use the virtual environment if you created one:

```powershell
.\.venv\Scripts\python.exe -m server --data-dir .\data-dev --port 8788
```

This is useful for testing. It does not install a service, does not start at boot, and
stores data in `./data-dev`. Do not use a development data directory for your real
devices.

---

## 4. Open the dashboard for the first time

1. On a device connected to the same LAN, open:

   ```text
   http://192.0.2.10:8787/
   ```

   Replace `192.0.2.10` with the controller's address. On the controller itself,
   `http://127.0.0.1:8787/` works.

2. Paste the **admin token** into the login screen and select **Connect to controller**.
   The token is exchanged for an HttpOnly, SameSite=Strict cookie. It is not stored in
   `localStorage`.

3. The Overview page opens. With no devices it shows zero counts and a pairing panel.

4. Open **Settings**. The pairing code is shown in the **Pairing** panel. Copy it with the
   button. You will use it on each new agent.

5. Keep the dashboard open while installing the first agent so you can approve it.

If the login fails, confirm that the token was copied without leading/trailing spaces and
that you are using the same controller data directory. Failed logins are rate-limited per
source IP; wait a minute before retrying many times.

### Optional phone view

Open `http://192.0.2.10:8787/lite` on a phone. It uses the same admin token and shows a
compact, read-only view. You can use **Add to Home screen** in the browser. The optional
native wrapper is described in [section 7.4](#74-optional-android-lite-viewer).

---

## 5. Add a Windows agent

Do this on the Windows PC you want to monitor. You need the HomeMonitor folder on that PC
and the controller URL and pairing code from section 4.

### 5.1 One-click install

1. Open the HomeMonitor folder in File Explorer.
2. Open `agents\windows`.
3. Double-click **Install HomeMonitor Agent.cmd**.
4. When prompted, enter:
   - Controller URL: `http://192.0.2.10:8787`
   - Pairing code: `ABCD-1234`
   - Device name: accept the computer name or type a friendly name.
5. The installer copies files to `%LOCALAPPDATA%\HomeMonitor\Agent`, creates a private
   Python environment, installs `psutil` (preferring bundled wheels if present), pairs the
   device and adds a startup shortcut.

Representative output:

```text
==> Checking Python
Using Python 3.12.10 at C:\Users\YOURNAME\AppData\Local\Programs\Python\Python312\python.exe
==> Installing files to C:\Users\YOURNAME\AppData\Local\HomeMonitor\Agent
==> Creating the local Python environment
==> Installing psutil from bundled wheels
==> Pairing 'Living Room PC' with http://192.0.2.10:8787
...
Pairing saved. Approve 'Living Room PC' in the dashboard.
==> Installing the current-user startup shortcut
==> Starting the agent in the background

HomeMonitor Windows agent installed.
  Device   : Living Room PC
  Server   : http://192.0.2.10:8787
  Agent    : C:\Users\YOURNAME\AppData\Local\HomeMonitor\Agent
  Config   : C:\Users\YOURNAME\AppData\Roaming\HomeMonitor\agent.json
  Log      : C:\Users\YOURNAME\AppData\Roaming\HomeMonitor\logs\agent.log
  Startup  : C:\Users\YOURNAME\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\HomeMonitor Agent.lnk
```

### 5.2 Approve the device

Return to the dashboard. The new device appears in the approval banner or under
**Settings -> Device access** with status **pending**. Select **Approve**.

Until approval, the controller accepts heartbeats but rejects metrics with
`pending_approval`. The agent logs that it is waiting and retries. After approval, within a
few seconds the card becomes **online** and CPU/RAM history begins.

### 5.3 Verify

- **Overview:** the device card shows current CPU, RAM, disk, network and uptime.
- **Device detail:** click the card for history, processes, disks, network and temperature
  (if available).
- **Log:** open `%APPDATA%\HomeMonitor\logs\agent.log` or double-click
  **View Agent Log.cmd**.

A healthy log contains lines similar to:

```text
2026-11-27 09:40:00 INFO    homemonitor.agent: HomeMonitor agent 1.0.0 starting as 'Living Room PC'
2026-11-27 09:40:00 INFO    homemonitor.agent: Controller: http://192.0.2.10:8787
2026-11-27 09:40:01 INFO    homemonitor.agent: Device approved; starting metrics upload
```

### 5.4 Auto-start and manual control

The installer creates a shortcut in the current user's Startup folder and a Start menu
shortcut. The agent starts when that user signs in. It does **not** run as a Windows
service before login and does not require administrator rights.

- **Run in console** (for diagnosis): `agents\windows\Run Agent in Console.cmd`.
- **Stop:** use Task Manager to end the `pythonw.exe` process whose command line contains
  `HomeMonitor\Agent`, or run the uninstaller.
- **Repair/update:** run the installer again. It keeps the existing token and database
  unless you pass `-ForcePair`.
- **Re-pair:** run with a new code:

  ```powershell
  powershell -ExecutionPolicy Bypass -File .\agents\windows\install.ps1 `
    -Controller http://192.0.2.10:8787 -PairingCode NEW-CODE -ForcePair
  ```

### 5.5 Unattended install

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\agents\windows\install.ps1 `
  -Controller http://192.0.2.10:8787 `
  -PairingCode ABCD-1234 `
  -Name "Living Room PC"
```

Useful switches: `-NoStartup`, `-NoLaunch`, `-ForcePair`, `-InstallDir PATH`.

---

## 6. Add an Ubuntu, Debian or Linux Mint agent

The same Python agent runs on all three distributions. The distribution entry points add
the correct detection and dependency handling; they are not renamed copies of the Windows
agent.

### 6.1 Install

1. Copy or extract HomeMonitor on the machine, for example to `~/HomeMonitor`.
2. Open a terminal in that folder.
3. Run the entry point for your distribution:

   **Ubuntu:**

   ```bash
   sudo bash agents/linux/ubuntu/install.sh \
     --controller http://192.0.2.10:8787 \
     --pairing-code ABCD-1234 \
     --name "Living Room PC"
   ```

   **Debian:**

   ```bash
   sudo bash agents/linux/debian/install.sh \
     --controller http://192.0.2.10:8787 \
     --pairing-code ABCD-1234 \
     --name "Living Room PC"
   ```

   **Linux Mint:**

   ```bash
   sudo bash agents/linux/linuxmint/install.sh \
     --controller http://192.0.2.10:8787 \
     --pairing-code ABCD-1234 \
     --name "Living Room PC"
   ```

   The wrappers add `--require-distro` and `--install-deps`, so apt installs
   `python3-venv`/`python3-psutil` if needed. To install on a compatible derivative, use:

   ```bash
   sudo bash agents/linux/install.sh --controller ... --pairing-code ... --name ...
   ```

4. The installer:
   - verifies systemd and Python 3.10+;
   - creates the system user `homemonitor-agent`;
   - installs to `/opt/homemonitor-agent`;
   - stores config/logs in `/var/lib/homemonitor-agent`;
   - pairs the device once with `--pair-only`;
   - installs and starts `homemonitor-agent.service` at boot.

Representative output:

```text
HomeMonitor agent installer
  Distribution : Ubuntu 24.04.1 LTS (24.04)
  Source       : /home/you/HomeMonitor
  Install dir  : /opt/homemonitor-agent
  Data dir     : /var/lib/homemonitor-agent
  Service user : homemonitor-agent
  Device name  : Living Room PC
  Controller   : http://192.0.2.10:8787
  Pairing      : enabled (code is not written to the service file)
...
Pairing the device with the controller...
Approve 'Living Room PC' in the controller dashboard.
Enabling and starting homemonitor-agent...
... active (running) ...
```

### 6.2 Approve and verify

Approve the pending device in the dashboard. Then:

```bash
sudo systemctl status homemonitor-agent --no-pager
sudo journalctl -u homemonitor-agent -n 30 --no-pager
sudo tail -f /var/lib/homemonitor-agent/logs/agent.log
```

Expected service state: `active (running)`, with a log line confirming the controller URL
and, after approval, `Device approved; starting metrics upload`.

Check the listening side: the agent makes outbound connections only. There should be no
inbound port open for the agent.

### 6.3 Operations

| Task | Command |
| --- | --- |
| Status | `sudo systemctl status homemonitor-agent` |
| Start at boot now | `sudo systemctl enable --now homemonitor-agent` |
| Restart | `sudo systemctl restart homemonitor-agent` |
| Stop temporarily | `sudo systemctl stop homemonitor-agent` |
| Follow logs | `sudo journalctl -u homemonitor-agent -f` |
| Config | `/var/lib/homemonitor-agent/agent.json` |
| File log | `/var/lib/homemonitor-agent/logs/agent.log` |
| Update files | Re-run the same installer command without a pairing code |
| Re-pair | Re-run with `--force-pair` and a fresh pairing code |

The service unit uses `NoNewPrivileges`, `ProtectSystem=strict`, `ProtectHome=true`,
private temporary storage and a restricted address-family list. The agent only needs
outbound IPv4/IPv6 and Unix sockets for Python internals.

### 6.4 If systemd is not available

The installer intentionally refuses to continue without systemd. Containers, WSL without
systemd and unusual init systems are not supported by the packaged service. You can still
run the agent manually for testing:

```bash
python3 -m pip install --user -r requirements-agent.txt
python3 -m agent --controller http://192.0.2.10:8787 --pairing-code ABCD-1234
```

Manual mode does not start at boot. Use the distribution's native service manager if you
need that.

---

## 7. Add an Android agent

The Android agent is a separate single-file, standard-library implementation. It does not
run the Windows code and does not need `psutil`.

### 7.1 Prepare Android

1. Install **Termux** and **Termux:Boot** from F-Droid:
   <https://f-droid.org/packages/com.termux/> and
   <https://f-droid.org/packages/com.termux.boot/>.
2. Open Termux:Boot once.
3. Disable battery optimisation for Termux and Termux:Boot:
   Settings -> Apps -> Termux -> Battery -> **Unrestricted**.
4. Optional: install **Termux:API** from F-Droid for SSID/battery details where the ROM
   exposes them.

### 7.2 Install the files and Python

Copy the HomeMonitor archive to the phone (USB, `adb push`, or download), then in Termux:

```bash
termux-setup-storage
cd ~
tar -xzf ~/storage/downloads/HomeMonitor-1.0.0.tar.gz
cd HomeMonitor-1.0.0
pkg update -y
pkg install -y python termux-api
python --version
```

If Python is already installed, `pkg install` is still safe. Python 3.8+ is enough for the
Android agent.

### 7.3 Prepare and pair

1. Run the setup script:

   ```bash
   bash agents/android/setup.sh
   ```

   This creates `~/.termux/boot/homemonitor-agent.sh`, which requests a wake lock and
   restarts the agent if it exits. It warns if Termux:Boot or Termux:API is missing.

2. Pair and start:

   ```bash
   bash agents/android/start.sh \
     --controller http://192.0.2.10:8787 \
     --pairing-code ABCD-1234 \
     --name "Android phone"
   ```

   The agent registers, saves its token to
   `~/.config/homemonitor/android_agent.json`, and starts reporting. Approve it in the
   dashboard. You can leave this foreground process running; the boot script is for the
   next reboot.

3. Check the log in another Termux session:

   ```bash
   tail -f ~/.config/homemonitor/android_agent.log
   ```

4. Test reboot persistence:

   ```bash
   reboot
   ```

   After the phone restarts, wait up to two minutes and check the dashboard. If it does not
   come back, see [Troubleshooting](#12-troubleshooting).

Expected Android limitations:

- Android 13+ may hide `/proc/stat` and `/proc/net/dev` from apps. CPU utilisation and
  network throughput can show as unavailable; RAM, storage, battery, temperature and
  frequency may still work.
- SSID and some battery fields require Termux:API and location permission. A missing value
  is shown as unavailable, never fabricated.
- Android TV boxes may report a dummy 100% battery. The agent suppresses obviously
  meaningless battery nodes.
- Aggressive vendor battery managers can still kill Termux. Use the wake lock, unrestricted
  battery mode and, if available, lock Termux in the recent-apps list.

### 7.4 Optional Android Lite viewer

This is **not** the agent. It is a small WebView wrapper for a controller running on the
same Android device (it opens `http://127.0.0.1:8787/lite`). Most users should simply open
`http://CONTROLLER_IP:8787/lite` in a browser and use **Add to Home screen**.

If you want the native wrapper:

```powershell
cd android-lite
.\build.ps1
.\build.ps1 -Install -Serial DEVICE_SERIAL
```

Requirements: JDK 17, Android SDK build-tools 34.0.0 and platform android-35. The first
build creates a local signing key. Never commit `keystore.jks` or `keystore.password`. The
viewer is optional, read-only and experimental; see
[android-lite/README.md](../android-lite/README.md).

---

## 8. Use the dashboard

The dashboard is served entirely by the controller; it works without internet access.

### Overview

- Controller status, LAN address, uptime and database size.
- Online/offline/pending counts.
- Device cards with CPU, RAM, disk, network, battery, temperature and Wi-Fi badges.
- Pending approval banner.
- Recent events and unresolved alerts.

### Devices

- Search by name, OS or IP.
- Open a device for current values, history charts, processes, disks, network details and
  events.
- Pending devices can be approved here as well.

### History

- Select a device and time window.
- Charts are rendered locally on a canvas; no chart library or external request is used.

### Alerts and events

- Offline/online transitions create events.
- Threshold alerts are stored and can be acknowledged.
- Retention is controlled by the settings page.

### Network

- Controller Wi-Fi/link information where the OS exposes it.
- Per-device IP, SSID, gateway, DNS, signal and link speed if reported.
- Router integration is not implemented; the page says so rather than showing fake data.

### Settings

- Pairing code and a copyable manual agent command.
- Heartbeat, metrics, offline threshold and retention settings.
- Device access: approve, revoke and delete.
- Controller platform, data directory, schema and version.

### Lite view

- `http://CONTROLLER_IP:8787/lite`
- Read-only, compact, refreshes every 5 seconds, uses the same admin session.
- Designed for a phone or a wall-mounted display. It cannot approve or revoke devices.

### Pairing lifecycle

1. Controller generates a pairing code.
2. Agent sends its UUID, name, OS and pairing code to `/api/v1/register`.
3. Controller creates a `pending` device and returns a device token.
4. Dashboard approves the device.
5. Heartbeats are always accepted for a valid device token; metrics are rejected until
   approval.
6. Revoking a device invalidates its token hash. Deleting a device also deletes its history.

The pairing code is not a device token and cannot be used to send metrics. Device identity
is the UUID, not the IP address.

---

## 9. Configure and maintain the system

### 9.1 Server configuration

Command-line flags and environment variables:

| Flag | Environment | Default | Notes |
| --- | --- | --- | --- |
| `--data-dir PATH` | `HOMEMONITOR_DATA_DIR` | `./data` | SQLite, tokens, logs |
| `--host ADDRESS` | `HOMEMONITOR_HOST` | `0.0.0.0` | Use `127.0.0.1` behind a local reverse proxy |
| `--port PORT` | `HOMEMONITOR_PORT` | `8787` | 1-65535 |
| `--no-discovery` | `HOMEMONITOR_DISCOVERY=0` | discovery on | UDP 45892 |
| `--pairing-code CODE` | `HOMEMONITOR_PAIRING_CODE` | generated | 4-32 letters/digits |
| - | `HOMEMONITOR_ADMIN_TOKEN` | generated | long random value |
| - | `HOMEMONITOR_DASHBOARD_DIR` | `./dashboard` | packaging override |

The Linux service reads `/etc/homemonitor/server.env`. The Windows installer writes the
port/bind values into its launcher; re-run it to change them. Termux uses the environment
of the shell that starts `server/termux/start.sh`.

### 9.2 Agent configuration

Desktop `agent.json`:

```json
{
  "controller_url": "http://192.0.2.10:8787",
  "device_id": "generated-uuid",
  "token": "generated-device-token",
  "name": "Living Room PC",
  "heartbeat_interval": 5,
  "metrics_interval": 5,
  "auto_discover": true
}
```

- Never share this file or commit it. The token is a credential.
- `heartbeat_interval` and `metrics_interval` are normally pushed by the controller; the
  values in the file are fallbacks/initial values.
- `auto_discover` allows UDP discovery after repeated connection failures. Set it to
  `false` if your network blocks broadcast or you want strictly explicit URLs.
- The device UUID is stable. Deleting and recreating it makes the controller treat the
  machine as a new device.

Android config: `~/.config/homemonitor/android_agent.json`, same fields minus the desktop
interval keys. The Android agent accepts `--controller`, `--pairing-code`, `--name`,
`--config`, `--discover` and `--once`.

### 9.3 Move the controller to a new address

1. Give the new host a DHCP reservation or static address.
2. Install/move the controller and its data directory.
3. Update each agent's `controller_url`, or re-run the installer with the new
   `--controller` value.
4. If the controller data directory was preserved, existing device tokens remain valid.
   If it was not preserved, every agent must pair again.
5. Open the dashboard and confirm devices become online.

### 9.4 Rotate the pairing code

Use **Settings -> Pairing -> Regenerate code** after onboarding. Existing paired devices
continue to work; only new registrations need the new code.

### 9.5 Revoke or delete a device

- **Revoke:** immediately invalidates the device token. The agent receives `403` and stops
  uploading until it is re-paired with a fresh code.
- **Delete:** removes the device and its history. This cannot be undone. Back up the
  database first if you may need the history.

### 9.6 Back up

Stop the service for a consistent copy, or use SQLite's online backup API.

**Linux controller:**

```bash
sudo systemctl stop homemonitor-controller
sudo cp -a /var/lib/homemonitor /var/backups/homemonitor-$(date +%F)
sudo systemctl start homemonitor-controller
```

**Windows controller** (PowerShell, close the server first):

```powershell
Stop-Process -Name pythonw -ErrorAction SilentlyContinue
Copy-Item "$env:LOCALAPPDATA\HomeMonitor\ServerData" `
  "$env:USERPROFILE\Desktop\HomeMonitor-backup" -Recurse
```

**Termux controller:**

```bash
tar -czf ~/homemonitor-backup-$(date +%F).tar.gz ~/.local/share/homemonitor
```

A backup contains the admin token, pairing code, hashed device tokens and monitoring
history. Encrypt it and store it somewhere private.

### 9.7 Restore

Stop the service, replace the data directory with the backup, keep the original
permissions/ownership, and start the service. On Linux:

```bash
sudo systemctl stop homemonitor-controller
sudo rm -rf /var/lib/homemonitor
sudo cp -a /var/backups/homemonitor-2026-11-27 /var/lib/homemonitor
sudo chown -R homemonitor:homemonitor /var/lib/homemonitor
sudo systemctl start homemonitor-controller
```

Existing agents keep working because their tokens are in the restored database.

### 9.8 Update

- **Source checkout:** stop the service, replace `server/`, `common/`, `dashboard/` and
  `agents/` with the new release, then restart. Keep the data directory.
- **Linux server:** re-run `sudo bash server/install-linux.sh`; the installer keeps
  `/var/lib/homemonitor` and `/etc/homemonitor/server.env`.
- **Windows server/agent:** run the installer again. It preserves the data/config unless
  you purge.
- **Android agent:** replace the project files, keep
  `~/.config/homemonitor/android_agent.json`, and restart the agent.
- **Android server:** replace the project files, keep the Termux data directory, and
  restart.

Always read `CHANGELOG.md` before a major update and take a backup first.

### 9.9 Health checks

- `GET /healthz` or `/api/v1/ping`: public JSON with version and time.
- Dashboard shows controller uptime and database size.
- The agent logs connection failures with backoff.
- The controller marks a device offline after `offline_after` seconds without a heartbeat.

---

## 10. Security and remote access

### Minimum checklist

- [ ] Controller on a trusted LAN, not port-forwarded.
- [ ] Windows firewall limited to the Private profile; Linux firewall limited to the LAN.
- [ ] Admin token unique and not stored in a note or screenshot.
- [ ] Pairing code regenerated after onboarding.
- [ ] Data directory readable only by the service account/current user.
- [ ] Unused devices revoked or deleted.
- [ ] Backups encrypted and access-controlled.
- [ ] Host OS and Python patched.

### What HomeMonitor does not provide

- TLS. The default URL is `http://`, and the session cookie has no `Secure` flag.
- User accounts or roles. Everyone with the admin token has full control.
- Public-internet hardening. The pairing code and token rate limits are not a substitute
  for a VPN or reverse proxy.
- Router/firewall configuration. You must scope access yourself.

### Remote access recommendation

Preferred: a VPN such as WireGuard or Tailscale. Keep the controller bound to the LAN and
connect the remote device to the VPN. Do not expose TCP 8787 directly.

If you must use a reverse proxy:

1. Bind HomeMonitor to `127.0.0.1` (or a private interface) and keep it off the public
   interface.
2. Terminate TLS at the proxy with a valid certificate.
3. Add authentication at the proxy in addition to the HomeMonitor token.
4. Restrict source addresses and rate-limit login/register endpoints.
5. Set secure proxy headers and avoid logging query strings/tokens.
6. Test from outside without using real credentials in shared logs.

Read [docs/REMOTE-ACCESS.md](REMOTE-ACCESS.md) for an example topology and caveats. There
is no hosted relay, no automatic certificate and no "just open a port" mode.

### Token handling

- The admin token is printed once at startup and stored in `config.json`. Treat it like a
  password.
- The dashboard session cookie lasts seven days. Use the logout action on shared browsers.
- Device tokens are stored only as SHA-256 hashes on the controller. The agent's
  `agent.json` contains the plaintext token; protect it with OS permissions.
- The SSE endpoint accepts a token in the query string for compatibility (`/api/v1/stream?
  token=...`). The dashboard uses the cookie. Do not put tokens in URLs that may be logged
  by a proxy.

---

## 11. Uninstall

Uninstalling an agent does not delete the device from the controller. Revoke/delete it in
the dashboard as well.

### 11.1 Windows agent

```powershell
.\agents\windows\Uninstall HomeMonitor Agent.cmd
```

This stops the agent, removes the startup/Start menu shortcuts and deletes the install
directory. It keeps `%APPDATA%\HomeMonitor` (config, token and logs). To delete those too:

```powershell
powershell -ExecutionPolicy Bypass -File .\agents\windows\uninstall.ps1 -RemoveConfig
```

### 11.2 Windows server

```powershell
.\server\windows\Uninstall HomeMonitor Server.cmd
```

Data and credentials remain in `%LOCALAPPDATA%\HomeMonitor\ServerData`. To remove them:

```powershell
powershell -ExecutionPolicy Bypass -File .\server\windows\uninstall-server.ps1 -Purge
```

Remove the firewall rule if you created one:

```powershell
Remove-NetFirewallRule -DisplayName "HomeMonitor (Private)"
```

### 11.3 Ubuntu / Debian / Linux Mint agent

From the extracted HomeMonitor folder:

```bash
sudo bash agents/linux/uninstall.sh
```

This removes the service and `/opt/homemonitor-agent`, but keeps the config/token and logs
in `/var/lib/homemonitor-agent`. For a complete removal:

```bash
sudo bash agents/linux/uninstall.sh --purge
```

`--purge` also deletes the service user.

### 11.4 Linux server

```bash
sudo bash server/uninstall-linux.sh
```

Keeps `/var/lib/homemonitor` and `/etc/homemonitor/server.env`. Complete removal:

```bash
sudo bash server/uninstall-linux.sh --purge
```

Remove the firewall allowance if you added one:

```bash
sudo ufw delete allow from YOUR_LAN_CIDR to any port 8787 proto tcp
```

### 11.5 Android agent

Inside Termux, from the project folder:

```bash
bash agents/android/uninstall.sh
```

This stops the process, removes the boot script, deletes the saved token and releases the
wake lock. It leaves the project files and `~/homemonitor-agent.log`. Delete those
manually if desired:

```bash
rm -rf ~/HomeMonitor-1.0.0 ~/homemonitor-agent.log
```

### 11.6 Android/Termux server

```bash
bash server/termux/uninstall.sh
```

Keeps the data directory. To delete the database, admin token and pairing code:

```bash
bash server/termux/uninstall.sh --purge
```

Then remove Termux and Termux:Boot through Android settings if you no longer need them.

### 11.7 Before disposing of a device

1. Revoke and delete the device in the controller.
2. Remove the agent config/token from the device.
3. Factory-reset or wipe storage as appropriate.
4. If the device was the controller, destroy/back up the data directory securely.

---

## 12. Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Dashboard does not load from another device | Firewall, wrong IP, AP isolation | Test `/healthz` locally; allow TCP 8787 on the private profile; disable client isolation |
| Login says invalid token | Copy/paste whitespace, wrong data dir, token rotated | Read `config.json` again; restart the correct server; wait if rate-limited |
| Agent says "No device token" | First run without a pairing code | Re-run with `--pairing-code` or set `HOMEMONITOR_PAIRING_CODE` |
| Pairing rejected | Old/invalid code, rate limit | Copy the current code from Settings; wait a minute; regenerate if needed |
| Device stuck pending | Not approved | Approve under Settings -> Device access |
| Device online but no CPU/RAM history | Not approved, or Android restricted `/proc` | Approve; check agent log; Android 13+ may report unavailable values |
| Agent cannot connect | Wrong URL, controller off, different network/VLAN | `curl http://CONTROLLER:8787/healthz` from the agent host |
| Agent works, then goes offline | Sleep, Wi-Fi power saving, Android battery manager | Disable sleep for the server; use wake lock/Termux:Boot/unrestricted battery |
| Linux installer says systemd missing | Container/WSL without systemd | Use a systemd VM/host or run the agent manually |
| Linux installer says Python too old | Distribution ships <3.10 | Install Python 3.10+ from a supported source |
| Windows installer cannot find Python | Python not on PATH / only a Store alias | Install from python.org or use `py -3`; reopen the shell |
| psutil install fails | No internet and no bundled wheels | Rebuild the platform package with wheels, or allow pip access |
| Port 8787 already in use | Another process/controller | `netstat -ano | findstr :8787` or `ss -ltnp | grep 8787`; choose another port |
| Dashboard shows stale data | Browser/SSE disconnected | Refresh; check controller logs; a reverse proxy may buffer SSE |
| Android dashboard unreachable after reboot | Termux:Boot not opened, battery optimisation | Open Termux:Boot once, set unrestricted, test the boot script manually |
| Android SSID shows unavailable | Missing location permission/Termux:API | Install Termux:API and grant location; not all ROMs expose SSID |
| High CPU on controller | Retention/DB too large or device polling too fast | Reduce retention, check DB size, keep intervals at 5-10 s |

More detail: [docs/TROUBLESHOOTING.md](TROUBLESHOOTING.md).

### Collect diagnostics for a bug report

```bash
python --version
python -m server --version 2>/dev/null || true
```

Include:

- HomeMonitor version.
- OS/distribution and version.
- Python version.
- Install method (package vs source).
- Relevant log lines with tokens, IPs and device names redacted.
- Whether it worked before and what changed.

Never attach a real database, `agent.json`, `config.json`, keystore or pairing code.

---

## 13. Validation status and limitations

The public release is honest about what was tested:

| Area | Status |
| --- | --- |
| Protocol, database, API and dashboard unit tests | 56 tests pass in this release |
| Windows 11 server + agent | Validated on physical hardware in the original deployment |
| Windows 10 | Implemented; not independently validated on a Windows 10 machine |
| Ubuntu/Debian/Mint systemd installers | Implemented; shell/unit validation only for this public tree |
| Linux agent collector | Shared code tested; not hardware-validated on every distribution |
| Android agent (Android 13) | Validated with the v1.0 agent before public packaging |
| Android/Termux server (older Android/Fire OS) | Validated in the original deployment |
| Android Lite viewer | Compiled; optional and not re-tested on every Android version |
| Remote access/TLS | Not built in; guidance only |
| Router integration, remote control, file access | Not implemented |

Before relying on an unvalidated path, run the install and monitor for at least a day,
including a reboot. Report the result with `docs/PLATFORMS.md` details.

Known limitations:

- Windows auto-start is at user sign-in, not before login.
- Linux auto-start requires systemd.
- Android background execution is controlled by the vendor; no app can guarantee it.
- The controller is HTTP-only unless you put it behind a TLS proxy.
- There is no built-in multi-user support.
- SQLite is the only storage backend.

---

## 14. Command reference

### Server

```bash
python -m server --help
python -m server --data-dir ./data-dev --port 8788 --no-discovery
curl http://127.0.0.1:8787/healthz
```

```powershell
powershell -File .\server\windows\install-server.ps1 -Port 8787 -Bind 0.0.0.0
powershell -File .\server\windows\uninstall-server.ps1 -Purge
Invoke-RestMethod http://127.0.0.1:8787/healthz
```

```bash
sudo bash server/install-linux.sh --port 8787
sudo systemctl status homemonitor-controller
sudo journalctl -u homemonitor-controller -f
sudo bash server/uninstall-linux.sh --purge
```

```bash
bash server/termux/setup.sh
bash server/termux/start.sh
bash server/termux/uninstall.sh --purge
```

### Desktop agent

```bash
python -m agent --help
python -m agent --controller http://192.0.2.10:8787 --pairing-code ABCD-1234 --pair-only
python -m agent --controller http://192.0.2.10:8787 --pairing-code ABCD-1234
python -m agent --once
python -m agent --discover
```

```powershell
powershell -File .\agents\windows\install.ps1 -Controller http://192.0.2.10:8787 -PairingCode ABCD-1234 -Name "Living Room PC"
powershell -File .\agents\windows\install.ps1 -Controller http://192.0.2.10:8787 -PairingCode NEW-CODE -ForcePair
powershell -File .\agents\windows\uninstall.ps1 -RemoveConfig
```

```bash
sudo bash agents/linux/ubuntu/install.sh --controller http://192.0.2.10:8787 --pairing-code ABCD-1234 --name "Living Room PC"
sudo bash agents/linux/install.sh --controller http://192.0.2.10:8787 --pairing-code NEW-CODE --force-pair
sudo systemctl status homemonitor-agent
sudo bash agents/linux/uninstall.sh --purge
```

### Android agent

```bash
bash agents/android/setup.sh
bash agents/android/start.sh --controller http://192.0.2.10:8787 --pairing-code ABCD-1234 --name "Android phone"
python agent/android_agent.py --once
bash agents/android/uninstall.sh
```

### Tests and release checks

```bash
python -m unittest discover -s tests -v
python -m compileall -q agent common server tests
python scripts/validate_repo.py
python scripts/package_release.py
```

The complete architecture, protocol, API and release notes are in the [docs](.) folder.

---

**You are done when:** the dashboard shows your device as online, the device card updates
at least every few seconds, and a reboot of the monitored device brings the agent back
automatically. If one of those is not true, use the troubleshooting table before exposing
the system to more devices.
