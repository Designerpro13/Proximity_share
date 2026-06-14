# Proximity Share — Key Workflows

## Application Startup

1. `main.py` calls `ProximityShareApp().run()`
2. `build()` initializes Config, NetworkDiscovery, TransferManager, SystemTrayManager
3. `Clock.schedule_once(_start_services, 0.1)`
4. `_start_services`: `NetworkDiscovery.start()`, `TransferManager.start()`
5. NetworkDiscovery registers mDNS service, starts ServiceBrowser
6. TransferManager starts worker thread

```mermaid
sequenceDiagram
    participant main as main.py
    participant App as ProximityShareApp
    participant Config
    participant ND as NetworkDiscovery
    participant TM as TransferManager
    participant ST as SystemTrayManager

    main->>App: ProximityShareApp().run()
    App->>App: build()
    App->>Config: Initialize
    App->>ND: Initialize
    App->>TM: Initialize
    App->>ST: Initialize
    App->>App: Clock.schedule_once(_start_services, 0.1)
    App->>ND: start()
    ND->>ND: Register mDNS service
    ND->>ND: Start ServiceBrowser
    App->>TM: start()
    TM->>TM: Start worker thread
```

## File Send Workflow

1. `queue_file(file_path, target_device)` → creates TransferItem with size-based priority
2. Worker thread dequeues item
3. `FileContainer.create_from_file()` packages the file
4. `TransferProtocol.send_file()` connects to peer TCP
5. Sends `FILE_OFFER`, waits for `FILE_ACCEPT`
6. Sends `FILE_DATA` (serialized container), waits for `FILE_ACK`
7. On failure: `retry_count++`, calculate exponential backoff delay, re-queue

```mermaid
sequenceDiagram
    participant Client as Sender
    participant TM as TransferManager
    participant FC as FileContainer
    participant TP as TransferProtocol
    participant Peer as Receiver

    Client->>TM: queue_file(file_path, target_device)
    TM->>TM: Create TransferItem (size-based priority)
    TM->>TM: Worker dequeues item
    TM->>FC: create_from_file(file_path)
    FC-->>TM: container bytes
    TM->>TP: send_file(container, target_device)
    TP->>Peer: TCP connect
    TP->>Peer: FILE_OFFER
    Peer-->>TP: FILE_ACCEPT
    TP->>Peer: FILE_DATA (serialized container)
    Peer-->>TP: FILE_ACK
    TP-->>TM: Success

    alt On Failure
        TP-->>TM: Error
        TM->>TM: retry_count++
        TM->>TM: backoff = min(30 * 2^(retry-1), 1800)
        TM->>TM: Re-queue with next_retry_time
    end
```

## File Receive Workflow

1. Protocol server accepts TCP connection
2. Reads 8-byte header (`msg_type` + `msg_size`)
3. On `FILE_OFFER`: auto-sends `FILE_ACCEPT`
4. On `FILE_DATA`: deserializes `FileContainer.from_bytes()`
5. Verifies SHA-256 checksum
6. Saves to shared folder (handles duplicates)
7. Sends `FILE_ACK`

```mermaid
sequenceDiagram
    participant Sender
    participant Server as Protocol Server
    participant FC as FileContainer
    participant FS as Filesystem

    Sender->>Server: TCP connect
    Sender->>Server: FILE_OFFER (8-byte header + payload)
    Server->>Server: Read header (msg_type + msg_size)
    Server-->>Sender: FILE_ACCEPT
    Sender->>Server: FILE_DATA (serialized container)
    Server->>FC: from_bytes(data)
    FC-->>Server: FileContainer instance
    Server->>Server: Verify SHA-256 checksum
    Server->>FS: Save to shared folder (handle duplicates)
    Server-->>Sender: FILE_ACK
```

## Device Discovery

1. Zeroconf registers `_proximityshare._tcp.local.` service
2. ServiceBrowser listens for peers
3. `P2PServiceListener.add_service` → stores in `discovered_devices`
4. `P2PServiceListener.remove_service` → removes from `discovered_devices`

```mermaid
sequenceDiagram
    participant App as ProximityShareApp
    participant ZC as Zeroconf
    participant SB as ServiceBrowser
    participant Listener as P2PServiceListener
    participant Network

    App->>ZC: Register _proximityshare._tcp.local.
    App->>SB: Start browsing for peers
    Network->>SB: Peer service appeared
    SB->>Listener: add_service(name, info)
    Listener->>Listener: Store in discovered_devices
    Network->>SB: Peer service removed
    SB->>Listener: remove_service(name)
    Listener->>Listener: Remove from discovered_devices
```

## Retry Logic

- Exponential backoff: `delay = min(30 * 2^(retry_count-1), 1800)`
- Items re-queued with `next_retry_time` set
- Worker skips items whose `next_retry_time > current time`
- Max 10 retries before permanent failure

```mermaid
sequenceDiagram
    participant Worker as Worker Thread
    participant Queue as PriorityQueue
    participant Item as TransferItem

    Worker->>Queue: Dequeue item
    Queue-->>Worker: TransferItem
    Worker->>Worker: Check next_retry_time <= now?
    alt Not ready yet
        Worker->>Queue: Re-queue (skip)
    else Ready
        Worker->>Worker: Attempt transfer
        alt Transfer fails
            Worker->>Item: retry_count++
            alt retry_count <= 10
                Worker->>Item: next_retry_time = now + min(30*2^(retry-1), 1800)
                Worker->>Queue: Re-queue item
            else retry_count > 10
                Worker->>Item: Mark permanent failure
            end
        end
    end
```
