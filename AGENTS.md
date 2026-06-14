# AGENTS.md — Proximity Share

## Project Overview

<!-- metadata:overview -->

Peer-to-peer desktop file sharing application using mDNS discovery and a custom TCP binary protocol. Python 3, Kivy framework. Runs as a system tray app with background transfer services.

**Entry point**: `main.py` → `ProximityShareApp().run()`

---

## Directory Map

<!-- metadata:directory -->

```
├── main.py                      # App entry, adds src/ to path, runs Kivy app
├── config/app.ini               # Static defaults (parsed by Config as base layer)
├── requirements.txt             # 6 runtime dependencies
├── src/
│   ├── __main__.py              # python -m src support
│   ├── core/app.py              # ProximityShareApp — lifecycle orchestrator
│   ├── network/discovery.py     # NetworkDiscovery — mDNS via zeroconf (real LAN IP)
│   ├── transfer/
│   │   ├── protocol.py          # TransferProtocol — TCP server+client, binary framing, encryption
│   │   ├── manager.py           # TransferManager — PriorityQueue + retry + starts server
│   │   └── container.py         # FileContainer — serialize/deserialize files
│   ├── security/encryption.py   # EncryptionManager — Fernet with per-session random salt
│   ├── ui/system_tray.py        # SystemTrayManager — BoxLayout UI + notifications
│   └── utils/config.py          # Config — INI defaults + JSON overrides
└── tests/                       # Empty (no tests yet)
```

---

## Subsystem Guide

<!-- metadata:subsystems -->

### Network Discovery (`src/network/`)

- Uses `zeroconf` library to register and browse `_proximityshare._tcp.local.` services
- `P2PServiceListener` receives add/remove callbacks → populates `discovered_devices` dict
- Hardcoded port `8888`, advertises hostname in TXT record

### Transfer Pipeline (`src/transfer/`)

- **Manager**: `PriorityQueue` with worker thread. Priority: 1 (<100KB), 2 (<10MB), 3 (≥10MB)
- **Protocol**: TCP binary framing — `[4B msg_type][4B msg_size][payload]` (network byte order)
  - Message types: HANDSHAKE(0x01), FILE_OFFER(0x02), ACCEPT(0x03), REJECT(0x04), DATA(0x05), ACK(0x06), ERROR(0xFF)
  - Flow: OFFER → ACCEPT → DATA → ACK
- **Container**: `[4B metadata_size][JSON metadata][raw bytes]` with SHA-256 integrity check
- **Retry**: exponential backoff `min(30 * 2^(n-1), 1800)` seconds, max 10 attempts

### Security (`src/security/`)

- `EncryptionManager` wraps `cryptography.fernet.Fernet`
- Key derived via PBKDF2HMAC (SHA256, 100k iterations, static salt)
- ⚠️ **Not integrated** — encrypt/decrypt methods exist but are never called in the transfer flow

### Configuration (`src/utils/`)

- Runtime: `~/.proximity_share/config.json` (shared_folder, port, max_retries, device_name, auto_accept, notifications)
- Static: `config/app.ini` exists but is **not parsed** by any code

---

## Patterns That Deviate from Defaults

<!-- metadata:deviations -->

- **No KivyMD usage** despite being in requirements.txt — UI uses plain Kivy widgets (BoxLayout, Label, ScrollView)
- **sys.path manipulation** in `main.py` — inserts `src/` so imports use bare module names (e.g., `from core.app import ...`)
- **Config layering** — `config/app.ini` provides static defaults, `~/.proximity_share/config.json` provides user overrides
- **Encryption uses device name as shared secret** — simplified pairing; proper key exchange is a future enhancement

---

## Implementation Gaps

<!-- metadata:gaps -->

| Gap | Impact | Status |
|-----|--------|--------|
| EncryptionManager not called in transfer pipeline | Files transfer unencrypted | ✅ Fixed — encrypt/decrypt wired into protocol |
| `config/app.ini` not parsed | Static config is dead code | ✅ Fixed — INI loaded as defaults layer |
| watchdog not imported anywhere | File monitoring not implemented | ⬜ Open |
| HANDSHAKE message defined but never sent/handled | Protocol incomplete | ✅ Fixed — full handshake flow |
| No tests | Zero test coverage | ⬜ Open |
| Context menu integration | Mentioned in DOCS.md but not implemented | ⬜ Open |
| Protocol server never started | Receiver can't accept connections | ✅ Fixed — started by TransferManager |
| mDNS registers 127.0.0.1 | Peers can't connect to this device | ✅ Fixed — auto-detects LAN IP |
| Auto-accept ignores config | Always accepts regardless of setting | ✅ Fixed — respects is_auto_accept_enabled() |
| device_name Windows-only | Uses COMPUTERNAME env var | ✅ Fixed — cross-platform detection |

---

## Detailed Documentation

<!-- metadata:docs -->

For deeper information, consult `.agents/summary/index.md` which routes to:

- `architecture.md` — layered design, threading model, design patterns
- `components.md` — all 10 classes with methods and relationships
- `interfaces.md` — full API signatures, binary protocol spec, mDNS interface
- `data_models.md` — wire formats, config schemas, entity relationships
- `workflows.md` — startup, send, receive, discovery, retry sequences (with Mermaid diagrams)
- `dependencies.md` — package purposes, stdlib usage, dependency graph

---

## Custom Instructions
<!-- This section is for human and agent-maintained operational knowledge.
     Add repo-specific conventions, gotchas, and workflow rules here.
     This section is preserved exactly as-is when re-running codebase-summary. -->
