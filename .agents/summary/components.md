# Proximity Share - Component Documentation

## Architecture Overview

```mermaid
classDiagram
    ProximityShareApp --> Config
    ProximityShareApp --> NetworkDiscovery
    ProximityShareApp --> TransferManager
    ProximityShareApp --> SystemTrayManager
    NetworkDiscovery --> P2PServiceListener
    TransferManager --> TransferItem
    TransferManager --> TransferProtocol
    TransferProtocol --> FileContainer
    TransferProtocol --> EncryptionManager
    FileContainer --> EncryptionManager

    class ProximityShareApp {
        +config: Config
        +network: NetworkDiscovery
        +transfer_manager: TransferManager
        +tray: SystemTrayManager
        +build() Widget
        +on_start()
        +on_stop()
    }

    class Config {
        +shared_folder: str
        +max_retries: int
        +port: int
        +auto_accept: bool
        +load()
        +save()
    }

    class NetworkDiscovery {
        +SERVICE_TYPE: str
        +zeroconf: Zeroconf
        +browser: ServiceBrowser
        +discovered_devices: dict
        +register()
        +unregister()
        +get_peers() list
    }

    class P2PServiceListener {
        +add_service()
        +remove_service()
        +update_service()
    }

    class TransferProtocol {
        +server_socket: socket
        +port: int
        +start_server()
        +stop_server()
        +send_file(peer, container)
        +_handle_client(conn)
    }

    class TransferManager {
        +queue: PriorityQueue
        +worker_thread: Thread
        +protocol: TransferProtocol
        +enqueue(file_path, target_device)
        +_worker()
        +_calculate_priority(size) int
        +_retry(item)
    }

    class TransferItem {
        +file_path: str
        +target_device: str
        +priority: int
        +retry_count: int
        +next_retry_time: float
        +container: FileContainer
        +__lt__(other) bool
    }

    class FileContainer {
        +filename: str
        +mime_type: str
        +timestamp: str
        +source_device: str
        +checksum: str
        +content_size: int
        +content: bytes
        +create_from_file(path)$ FileContainer
        +create_from_text(text)$ FileContainer
        +serialize() bytes
        +deserialize(data)$ FileContainer
        +verify_integrity() bool
        +save(directory)
    }

    class EncryptionManager {
        +fernet: Fernet
        +derive_key(password) bytes
        +encrypt(data) bytes
        +decrypt(data) bytes
    }

    class SystemTrayManager {
        +build() Widget
        +notify(title, message)
    }
```

## Components

### 1. ProximityShareApp (`src/core/app.py`)

Kivy `App` subclass that orchestrates the full application lifecycle.

- **Initializes**: Config, NetworkDiscovery, TransferManager, SystemTrayManager
- **Deferred start**: Uses `Clock.schedule_once` to start network services after the UI event loop is running
- **Lifecycle**: `on_start()` triggers discovery and transfer server; `on_stop()` tears down all services

---

### 2. NetworkDiscovery (`src/network/discovery.py`)

Handles mDNS-based automatic device discovery on the local network.

- **SERVICE_TYPE**: `_proximityshare._tcp.local.`
- **Dependencies**: `zeroconf.Zeroconf`, `ServiceBrowser`, `ServiceInfo`
- **Behavior**: Registers this device as a service, browses for peers, maintains a `discovered_devices` dict keyed by device name

```mermaid
classDiagram
    NetworkDiscovery --> P2PServiceListener
    NetworkDiscovery --> Zeroconf
    NetworkDiscovery --> ServiceBrowser
    NetworkDiscovery --> ServiceInfo

    class NetworkDiscovery {
        +SERVICE_TYPE: "_proximityshare._tcp.local."
        +zeroconf: Zeroconf
        +browser: ServiceBrowser
        +info: ServiceInfo
        +discovered_devices: dict
        +register()
        +unregister()
    }

    class P2PServiceListener {
        +discovery: NetworkDiscovery
        +add_service(zc, type_, name)
        +remove_service(zc, type_, name)
        +update_service(zc, type_, name)
    }

    class Zeroconf {
        <<external>>
    }
    class ServiceBrowser {
        <<external>>
    }
    class ServiceInfo {
        <<external>>
    }
```

---

### 3. P2PServiceListener (`src/network/discovery.py`)

Implements `zeroconf.ServiceListener` interface.

- **add_service**: Resolves service info, adds peer to `discovered_devices`
- **remove_service**: Removes peer from `discovered_devices`

---

### 4. TransferProtocol (`src/transfer/protocol.py`)

TCP-based binary protocol for file transfer between peers.

- **Server**: Threaded TCP socket server accepting incoming transfers
- **Binary header**: 8 bytes total — 4B message type + 4B message size (network-order `uint32`)

```mermaid
classDiagram
    class TransferProtocol {
        +server_socket: socket
        +port: int
        +running: bool
        +start_server()
        +stop_server()
        +send_file(peer_address, container)
        +_handle_client(conn, addr)
        +_send_message(sock, msg_type, payload)
        +_recv_message(sock) tuple
    }

    class MessageType {
        <<enumeration>>
        HANDSHAKE = 0x01
        FILE_OFFER = 0x02
        FILE_ACCEPT = 0x03
        FILE_REJECT = 0x04
        FILE_DATA = 0x05
        FILE_ACK = 0x06
        ERROR = 0xFF
    }

    TransferProtocol --> MessageType
```

**Transfer flow** (`send_file()`):
1. Connect to peer
2. Send `FILE_OFFER` with file metadata
3. Wait for `FILE_ACCEPT` or `FILE_REJECT`
4. On accept: send `FILE_DATA` with serialized container bytes
5. Wait for `FILE_ACK`

---

### 5. TransferManager (`src/transfer/manager.py`)

Priority-based transfer queue with automatic retry logic.

- **Queue**: `PriorityQueue` with background worker thread
- **Priority assignment**:
  - Priority 1: files < 100KB
  - Priority 2: files < 10MB
  - Priority 3: files ≥ 10MB
- **Retry policy**: Exponential backoff, base delay 30s, max delay 1800s, max 10 attempts

```mermaid
classDiagram
    TransferManager --> TransferItem
    TransferManager --> TransferProtocol

    class TransferManager {
        +queue: PriorityQueue
        +worker_thread: Thread
        +protocol: TransferProtocol
        +running: bool
        +enqueue(file_path, target_device)
        +start()
        +stop()
        -_worker()
        -_calculate_priority(file_size) int
        -_retry(item: TransferItem)
        -_backoff_delay(retry_count) float
    }

    class TransferItem {
        +file_path: str
        +target_device: str
        +priority: int
        +retry_count: int
        +next_retry_time: float
        +container: FileContainer
        +__lt__(other) bool
    }
```

---

### 6. TransferItem (`src/transfer/manager.py`)

Dataclass-like object representing a single queued transfer.

| Field | Type | Description |
|-------|------|-------------|
| `file_path` | `str` | Path to source file |
| `target_device` | `str` | Destination peer identifier |
| `priority` | `int` | Queue priority (1=highest) |
| `retry_count` | `int` | Number of retries attempted |
| `next_retry_time` | `float` | Timestamp for next retry |
| `container` | `FileContainer` | Serialized file container |

Implements `__lt__` for `PriorityQueue` ordering by priority value.

---

### 7. FileContainer (`src/transfer/container.py`)

Cross-platform binary file format for transfer.

**Serialization format**:
```
[4B metadata_size (big-endian)] [JSON metadata] [raw file content]
```

**Metadata fields**:
- `filename` — original file name
- `mime_type` — detected MIME type
- `timestamp` — ISO creation timestamp
- `source_device` — sender device name
- `checksum` — SHA-256 hex digest
- `content_size` — byte count of raw content

```mermaid
classDiagram
    class FileContainer {
        +filename: str
        +mime_type: str
        +timestamp: str
        +source_device: str
        +checksum: str
        +content_size: int
        +content: bytes
        +create_from_file(path)$ FileContainer
        +create_from_text(text, filename)$ FileContainer
        +serialize() bytes
        +deserialize(data)$ FileContainer
        +verify_integrity() bool
        +save(directory) str
        -_generate_checksum(data) str
        -_resolve_filename(directory, filename) str
    }
```

- **Integrity**: SHA-256 checksum verified on deserialization
- **Duplicate handling**: Counter-based rename (e.g., `file(1).txt`, `file(2).txt`)

---

### 8. EncryptionManager (`src/security/encryption.py`)

Symmetric encryption layer for file transfer security.

- **Algorithm**: Fernet (AES-128-CBC with HMAC-SHA256)
- **Key derivation**: PBKDF2HMAC with SHA256, 100,000 iterations, static salt
- **Note**: Uses a default password placeholder (to be replaced with device pairing exchange)

```mermaid
classDiagram
    class EncryptionManager {
        +fernet: Fernet
        -_key: bytes
        +__init__(password: str)
        +derive_key(password, salt) bytes
        +encrypt(data: bytes) bytes
        +decrypt(data: bytes) bytes
    }
```

---

### 9. SystemTrayManager (`src/ui/system_tray.py`)

Desktop integration providing system tray presence and notifications.

- **UI**: Returns a root Kivy `Label` widget (placeholder for future full UI)
- **Notifications**: Uses `plyer.notification` for cross-platform desktop notifications

```mermaid
classDiagram
    class SystemTrayManager {
        +build() Widget
        +notify(title: str, message: str)
    }
```

---

### 10. Config (`src/utils/config.py`)

Application configuration management with JSON persistence.

- **Path**: `~/.proximity_share/config.json`
- **Auto-creates** config directory and shared folder on first run

| Setting | Default | Description |
|---------|---------|-------------|
| `shared_folder` | `~/Proximity_Shared/` | Received files destination |
| `max_retries` | `10` | Maximum transfer retry attempts |
| `port` | `8888` | TCP listening port |
| `auto_accept` | `true` | Auto-accept incoming transfers |

```mermaid
classDiagram
    class Config {
        +config_path: str
        +shared_folder: str
        +max_retries: int
        +port: int
        +auto_accept: bool
        +load()
        +save()
        +get(key) any
        +set(key, value)
        -_ensure_directories()
        -_defaults() dict
    }
```
