# Video Streaming with RTSP & RTP

## Overview
This project implements a simple **video streaming system** using **RTSP (Real-Time Streaming Protocol)** for control and **RTP (Real-Time Transport Protocol)** for media delivery.

The system follows a **client–server architecture** where the client sends RTSP commands to control video playback while the server streams MJPEG video frames encapsulated in RTP packets.

The main objectives of this project are:

- Implement **RTSP protocol logic on the client side**
- Implement **RTP packetization on the server side**
- Stream **MJPEG video frames** over the network
- Demonstrate basic **multimedia streaming over sockets**

---

## System Architecture

The system consists of two communication channels:

### 1. Control Channel – RTSP (TCP)
RTSP is used to control the streaming session.

- Protocol: **TCP**
- Default port: **554** (custom port >1024 used in this project)
- Supported commands:
  - `SETUP`
  - `PLAY`
  - `PAUSE`
  - `TEARDOWN`

TCP ensures **reliable delivery of control messages**.

### 2. Media Channel – RTP (UDP / TCP)

The actual video data is transmitted using RTP.

- Default transport: **RTP over UDP**
- Advantage: **low latency**
- Limitation: **possible packet loss**

For **HD streaming (720p / 1080p)** the system can switch to **RTP over TCP** to improve reliability.

---

## Project Structure
```bash
.
├── ClientLauncher.py   # Launches the client GUI
├── Client.py           # RTSP client implementation and video player
├── Server.py           # RTSP server entry point
├── ServerWorker.py     # Handles client requests and streams video
├── RtpPacket.py        # RTP packet encoding and decoding
├── VideoStream.py      # Reads frames from MJPEG video files
├── Utils.py            # Utility functions
├── cache/              # Temporary cached frames for buffering
└── videos/             # Example SD, HD videos
```

### Client Components

**ClientLauncher**
- Starts the client application
- Provides the GUI interface
- Sends RTSP commands via buttons

**Client**
- Handles RTSP communication with the server
- Implements actions for:
  - `SETUP`
  - `PLAY`
  - `PAUSE`
  - `TEARDOWN`
- Receives RTP packets and displays video frames

---

### Server Components

**Server**
- Listens for RTSP connections
- Creates a worker thread for each client

**ServerWorker**
- Handles RTSP requests
- Streams video frames when receiving `PLAY`

---

### RTP Packet Module

**RtpPacket**
- Responsible for **RTP packet creation and decoding**
- Header size: **12 bytes**
- Payload: **one MJPEG frame**

Fields implemented:

- Version (V) = **2**
- Payload Type (PT) = **26 (MJPEG)**
- Sequence Number
- Timestamp
- SSRC (Server Identifier)

---

### VideoStream

Reads video frames from a **.Mjpeg file** stored on disk.

Each frame is read sequentially and sent to the client.

---

## RTSP Session Flow

Typical interaction between client and server:

1. **SETUP**
   - Establish session
   - Configure RTP transport parameters

2. **PLAY**
   - Start streaming video

3. **PAUSE**
   - Temporarily stop playback

4. **TEARDOWN**
   - Terminate session

Example:
```bash
C: SETUP movie.Mjpeg RTSP/1.0
C: CSeq: 1
C: Transport: RTP/UDP; client_port=25000

S: RTSP/1.0 200 OK
S: CSeq: 1
S: Session: 123456
```

## Running the Project

### 1. Start the Server

```bash
python3 Server.py <server_port>
```

### 2. Start the Client

```bash
python3 ClientLauncher.py <server_host> <server_port> <rtp_port> <video_file>
```