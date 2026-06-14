# Proximity Share

Peer-to-peer file sharing between personal devices on the same LAN. Zero cloud, zero accounts — just drop files across your machines.

## Features

- **Auto-discovery** — finds peers via mDNS (zero-config networking)
- **Encrypted transfers** — Fernet (AES-128-CBC) with PBKDF2 key derivation
- **Binary protocol** — HANDSHAKE → OFFER → ACCEPT → DATA → ACK flow
- **Priority queue** — small files first, exponential backoff retries
- **Integrity checks** — SHA-256 per file container
- **Desktop notifications** — via plyer
- **Minimal UI** — Kivy widget showing discovered devices and transfer log

## Quick Start

```bash
pip install -r requirements.txt
python main.py
```

Or as a package:

```bash
python -m src
```

## How It Works

1. On startup the app registers itself as `_proximityshare._tcp.local.` via mDNS
2. Other instances on the LAN are discovered automatically
3. To send a file, queue it programmatically:
   ```python
   app.send_file("/path/to/file.pdf", "192.168.1.42")
   ```
4. Sender performs HANDSHAKE, offers the file, encrypts + sends on acceptance
5. Receiver verifies integrity, decrypts, and saves to `~/Proximity_Shared/`

## Project Structure

```
├── main.py                      # Entry point
├── config/app.ini               # Static defaults (parsed at startup)
├── requirements.txt             # Runtime dependencies
└── src/
    ├── __main__.py              # python -m src support
    ├── core/app.py              # ProximityShareApp — lifecycle orchestrator
    ├── network/discovery.py     # mDNS advertisement + browsing
    ├── transfer/
    │   ├── protocol.py          # TCP binary protocol (server + client)
    │   ├── manager.py           # Priority queue + retry worker
    │   └── container.py         # File serialization with metadata
    ├── security/encryption.py   # Fernet encryption with per-session salt
    ├── ui/system_tray.py        # Kivy UI + desktop notifications
    └── utils/config.py          # Config (INI defaults → JSON overrides)
```

## Configuration

Config is loaded in layers (later wins):

1. Hardcoded defaults
2. `config/app.ini` (static, version-controlled)
3. `~/.proximity_share/config.json` (user-specific overrides)

### User config keys

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `shared_folder` | path | `~/Proximity_Shared` | Where received files land |
| `port` | int | 8888 | TCP listen port |
| `device_name` | string | hostname | How this device appears to peers |
| `auto_accept_files` | bool | true | Accept incoming files without prompt |
| `max_retries` | int | 10 | Send retry limit per file |
| `notification_enabled` | bool | true | Show desktop notifications |

## Protocol (v2)

```
[4B msg_type][4B payload_size][payload]
```

| Type | Code | Direction |
|------|------|-----------|
| HANDSHAKE | 0x01 | both |
| FILE_OFFER | 0x02 | sender → receiver |
| FILE_ACCEPT | 0x03 | receiver → sender |
| FILE_REJECT | 0x04 | receiver → sender |
| FILE_DATA | 0x05 | sender → receiver |
| FILE_ACK | 0x06 | receiver → sender |
| ERROR | 0xFF | either |

## Development

```bash
# Install dev deps (if you add a test framework later)
pip install -r requirements.txt

# Run
python main.py
```

## License

Personal project — do whatever you want with it.
