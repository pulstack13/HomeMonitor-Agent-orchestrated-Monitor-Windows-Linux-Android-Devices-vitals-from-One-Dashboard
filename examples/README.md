# Examples

Copy these examples, replace every placeholder, and keep the filled-in copies out of
version control. They contain no real credentials by design.

| File | Purpose |
| --- | --- |
| `server.env.example` | Environment file for a Linux systemd controller |
| `server-windows.ps1` | Start a controller from source on Windows with overrides |
| `agent-windows.json` | Desktop agent config shape (Windows) |
| `agent-linux.json` | Desktop agent config shape (Linux) |
| `agent-android.json` | Android agent config shape |
| `api.sh` | Admin API calls with curl |
| `api.ps1` | Admin API calls with PowerShell |

Never commit a filled-in `agent.json`, `server.env`, token or pairing code. The
`.gitignore` covers the common names, but it is not a substitute for care.

The example addresses use the documentation range `192.0.2.0/24`.
