# Proximity Share - System Architecture

## High-Level Architecture

- Kivy application with modular package structure
- Event-driven with background threads for network and transfer
- Layered: UI → Core → Network/Transfer/Security → Utils

```mermaid
graph TD
    UI[UI Layer<br>src/ui/system_tray.py]
    Core[Core Layer<br>src/core/app.py]
    Network[Network<br>src/network/discovery.py]
    Transfer[Transfer<br>src/transfer/]
    Security[Security<br>src/security/encryption.py]
    Utils[Utils<br>src/utils/config.py]

    UI --> Core
    Core --> Network
    Core --> Transfer
    Core --> Security
    Network --> Utils
    Transfer --> Utils
    Security --> Utils
```

## Package Structure

| Module | Class(es) | Responsibility |
|--------|-----------|----------------|
| `src/core/app.py` | `ProximityShareApp` | Main Kivy App, orchestrates all services |
| `src/network/discovery.py` | `NetworkDiscovery`, `P2PServiceListener` | mDNS device discovery via zeroconf |
| `src/transfer/protocol.py` | `TransferProtocol` | TCP server/client, binary message framing |
| `src/transfer/manager.py` | `TransferManager`, `TransferItem` | PriorityQueue-based transfer scheduling, retry logic |
| `src/transfer/container.py` | `FileContainer` | Serialization format with integrity checks |
| `src/security/encryption.py` | `EncryptionManager` | Fernet symmetric encryption, PBKDF2 key derivation |
| `src/ui/system_tray.py` | `SystemTrayManager` | Kivy widget + plyer notifications |
| `src/utils/config.py` | `Config` | JSON config management with defaults |

```mermaid
classDiagram
    class ProximityShareApp {
        +discovery: NetworkDiscovery
        +transfer_manager: TransferManager
        +protocol: TransferProtocol
        +encryption: EncryptionManager
        +tray: SystemTrayManager
        +config: Config
        +build()
        +on_start()
        +on_stop()
    }

    class NetworkDiscovery {
        +browser: ServiceBrowser
        +listener: P2PServiceListener
        +start_discovery()
        +stop_discovery()
        +get_peers()
    }

    class P2PServiceListener {
        +add_service()
        +remove_service()
        +update_service()
    }

    class TransferProtocol {
        +start_server()
        +stop_server()
        +send_file()
        +handle_client()
    }

    class TransferManager {
        +queue: PriorityQueue
        +add_transfer()
        +process_queue()
        +retry_transfer()
    }

    class TransferItem {
        +file_path: str
        +priority: int
        +retries: int
        +status: str
    }

    class FileContainer {
        +pack()
        +unpack()
        +verify_integrity()
    }

    class EncryptionManager {
        +encrypt_file()
        +decrypt_file()
        +derive_key()
    }

    class SystemTrayManager {
        +show_notification()
        +update_status()
    }

    class Config {
        +load()
        +save()
        +get()
        +set()
    }

    ProximityShareApp --> NetworkDiscovery
    ProximityShareApp --> TransferManager
    ProximityShareApp --> TransferProtocol
    ProximityShareApp --> EncryptionManager
    ProximityShareApp --> SystemTrayManager
    ProximityShareApp --> Config
    NetworkDiscovery --> P2PServiceListener
    TransferManager --> TransferItem
    TransferProtocol --> FileContainer
    TransferProtocol --> EncryptionManager
```

## Design Patterns

| Pattern | Application |
|---------|-------------|
| **Observer** | `P2PServiceListener` reacts to mDNS service add/remove/update events |
| **Producer-Consumer** | `TransferManager` queue with dedicated worker thread consuming items |
| **Facade** | `ProximityShareApp` provides unified interface to all subsystems |
| **Strategy** | Priority assignment based on file size for transfer scheduling |

```mermaid
sequenceDiagram
    participant User
    participant App as ProximityShareApp
    participant TM as TransferManager
    participant TP as TransferProtocol
    participant EM as EncryptionManager
    participant FC as FileContainer

    User->>App: Send file
    App->>TM: add_transfer(file, peer, priority)
    TM->>TM: Enqueue to PriorityQueue
    TM->>FC: pack(file)
    FC-->>TM: container bytes
    TM->>EM: encrypt_file(container)
    EM-->>TM: encrypted payload
    TM->>TP: send_file(peer, payload)
    TP-->>TM: transfer result
    alt Transfer failed
        TM->>TM: retry_transfer()
    end
    TM-->>App: Status update
    App-->>User: Notification
```

## Threading Model

- **Main thread**: Kivy event loop (UI rendering, user interaction)
- **Discovery thread**: Managed by zeroconf `ServiceBrowser`
- **Transfer worker thread**: Processes `PriorityQueue` items sequentially
- **Protocol server thread**: Accepts incoming TCP connections
- **Per-client handler threads**: Spawned per inbound connection

```mermaid
graph LR
    subgraph Main Thread
        Kivy[Kivy Event Loop]
    end

    subgraph Background Threads
        DT[Discovery Thread<br>zeroconf ServiceBrowser]
        TW[Transfer Worker Thread<br>PriorityQueue consumer]
        PS[Protocol Server Thread<br>TCP accept loop]
    end

    subgraph Spawned Threads
        CH1[Client Handler 1]
        CH2[Client Handler 2]
        CHn[Client Handler N]
    end

    Kivy -->|schedules| TW
    Kivy -->|starts/stops| DT
    Kivy -->|starts/stops| PS
    PS -->|spawns| CH1
    PS -->|spawns| CH2
    PS -->|spawns| CHn
    DT -->|callbacks| Kivy
    TW -->|status updates| Kivy
    CH1 -->|received file| Kivy
```
