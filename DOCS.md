# Proximity Share

A personal device-to-device sharing solution that enables seamless transfer of various file types including text, documents, URLs, and images between your devices.

## Project Overview

### Vision

Create a fast, secure, offline-first file transfer system that works across personal devices (desktop/mobile) with a "fire-and-forget" sharing philosophy, removing the friction from cross-device workflows.

### Core Problems Solved

- Enabling mordern file format sharing ( markdown file transfer not supported by traditional Bluetooth FTP)
- Nullify dependancy on 3rd-party apps like WA or Drive for strictly P2P sharing.
- Allowing quick sharing of text snippets and URLs
- Creating a frictionless sharing experience between personal devices
- Supporting various file types with appropriate handling

### Key Principles

- **Offline-first**: Works without internet, direct device-to-device
- **Fire-and-forget**: Share and move on, system handles delivery
- **True P2P**: No master device, any device can share with any other
- **Simplicity**: Minimal UI, integrates with existing system paradigms

## Technical Architecture

### Technology Stack

#### Desktop Components

- **Core Protocol Engine**: Python
  - Network discovery
  - File transfer protocol
  - Containerization
  - Retry mechanism
- **Desktop UI**: Kivy (Python)
  - System tray application
  - Transfer progress visualization
  - Folder monitoring
  - Context menu integration

#### Mobile Components

- **Android App**: Kotlin
  - Native share integration
  - Background service
  - File management
  - Transfer protocol client

### Communication Protocol

#### Network Layer

- WiFi Direct (primary) - High speed, direct device-to-device
- Bluetooth (fallback) - Universal compatibility
- Local network discovery via multicast DNS (mDNS)

#### Transfer Protocol

- Custom binary protocol with:
  - Metadata header (file type, size, checksum)
  - Content payload (containerized)
  - Acknowledgment system
  - Retry mechanism with exponential backoff

#### Security Layer

- End-to-end encryption
- Pre-shared keys between personal devices
- Container format to preserve file integrity

## Functional Specifications

### Core Functionality

#### File Transfer

- Support for text files (.txt, .md)
- Support for documents (.pdf, .docx)
- Support for images (.png, .jpg)
- Support for URLs and web bookmarks
- Support for plain text snippets

#### Transfer Management

- Timeout-based cyclic retry system
  - Initial retry: 30 seconds
  - Subsequent retries: Doubled interval (1 min, 2 min, etc.)
  - Maximum retry interval: 30 minutes
  - Maximum retry attempts: Configurable
- Size-based queuing:
  - Small files (< 100KB) first
  - Medium files (< 10MB) second
  - Large files last

#### Containerization

- Custom lightweight container format
- Includes:
  - Original filename
  - MIME type
  - Timestamp
  - Source device identifier
  - Checksum
- Ensures cross-platform compatibility
- Preserves file integrity

### User Interface & Experience

#### Desktop

- **Context Menu Integration**:
  - Right-click on files → "Share using Proximity"
  - Right-click on selected text → "Share using Proximity"
- **System Tray Application**:
  - Transfer status
  - Device discovery
  - Preferences
- **Shared Folder**:
  - Designated folder for received files
  - Automatically organized by type/date

#### Mobile (Android)

- **Share Sheet Integration**:
  - "Share using Proximity" option in system share menu
- **App UI**:
  - Simple list of received files
  - Transfer status
  - Device management
- **Background Service**:
  - Runs minimally to preserve battery
  - Wakes on network events
  - Notification for received files

### File Handling Specifics

#### Text & URLs

- URLs detected and converted to clickable links
- Markdown files preserved with formatting
- Text snippets saved as .txt files

#### Duplicate Handling

- Auto-rename with timestamp or copy number suffix
- Handled on receiver side
- User-configurable policy (overwrite/rename/ignore)

## Non-Functional Specifications

### Performance

- **Transfer Speed**:
  - WiFi Direct: Up to 250Mbps
  - Bluetooth: 2-3Mbps
- **Startup Time**:
  - Desktop service: < 2 seconds
  - Android background service: < 3 seconds
- **Battery Impact**:
  - Minimal when idle (wake on network events)
  - Moderate during active transfer

### Reliability

- Persistent retry mechanism ensures delivery
- Checksum verification of all transfers
- Queue persistence across application restarts

### Security

- End-to-end encryption for all transfers
- No data stored on third-party servers
- Optional PIN confirmation for sensitive transfers

### Compatibility

- **Desktop**: Windows 10+, Linux (major distributions)
- **Mobile**: Android 8.0+

## Implementation Plan

### Phase 1: Core Protocol Development

1. Set up Python environment and project structure
2. Implement network discovery using mDNS
3. Create file containerization format
4. Develop basic transfer protocol
5. Build retry and acknowledgment system
6. Create command-line interface for testing

### Phase 2: Desktop Experience

1. Develop Kivy-based system tray application
2. Implement context menu integration for Windows/Linux
3. Create shared folder monitoring
4. Add transfer progress visualization
5. Build preferences system
6. Test end-to-end on desktop platforms

### Phase 3: Mobile Integration

1. Set up Kotlin Android project
2. Implement background service for receiving files
3. Create share sheet integration
4. Develop mobile UI
5. Integrate with core protocol
6. Test cross-device transfers

### Phase 4: Refinement & Optimization

1. Performance optimization
2. Battery usage analysis on mobile
3. Error handling improvements
4. User experience refinements
5. Packaging and deployment

## Typical Workflows

### Desktop to Mobile

1. User right-clicks a file on desktop
2. Selects "Share using Proximity" → "Mobile"
3. File is queued for transfer
4. When devices connect, file transfers automatically
5. Android notification appears when complete
6. File is accessible in the app and through file system

### Mobile to Desktop

1. User views content in an app (document, image, URL)
2. Taps "Share" → "Share using Proximity" → "Desktop"
3. Android app queues the file
4. When devices connect, file transfers automatically
5. File appears in desktop's shared folder
6. Optional desktop notification

### Text Snippet Sharing

1. User selects text on either device
2. Shares via context menu or share sheet
3. Text appears as a .txt file on receiving device
4. Dated and timestamped for reference

## Technical Challenges & Solutions

### Challenge: Device Discovery

**Solution**: Multicast DNS (mDNS) for local network discovery with device fingerprinting

### Challenge: Cross-Platform Compatibility

**Solution**: Custom container format that preserves file metadata

### Challenge: Battery Optimization

**Solution**: Wake-on-packet technique with minimal background service

### Challenge: Connection Resilience

**Solution**: Smart retry system with exponential backoff

### Challenge: Security

**Solution**: End-to-end encryption with pre-shared keys

## Future Enhancements

### Network Hopping

Allow transfers via intermediate devices when direct connection isn't possible

---

*This document will evolve as the project progresses. Last updated: August 22, 2025.*
