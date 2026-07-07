# Lazarus Guard\nFace-recognition security system. Part of Project Nexus: Dozor.
<div align="center">

# 🛡️ Lazarus Guard

**Face-recognition security system with real-time multi-device deployment**

Part of [Project Nexus: Dozor](https://github.com/AyamGorengMadura/nexus-core)

![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=flat-square&logo=python&logoColor=white)
![MediaPipe](https://img.shields.io/badge/MediaPipe-Latest-00A98F?style=flat-square&logo=google&logoColor=white)
![License](https://img.shields.io/badge/License-Private-red?style=flat-square)
![Status](https://img.shields.io/badge/Status-Active%20Development-yellow?style=flat-square)
![Version](https://img.shields.io/badge/Version-4.x-blue?style=flat-square)

</div>

---

## 📖 Overview

Lazarus Guard is a modular face-recognition security system built on 936-dimensional normalized facial landmark embeddings. It uses cosine similarity matching with averaged top-3 scoring for robust identification, designed for edge deployment across multiple devices.

## 🏗️ Architecture

```mermaid
graph TB
    subgraph Input Layer
        CAM[📷 Webcam/IP Camera]
        MULTI[📡 Multi-Device Input]
    end

    subgraph Processing Pipeline
        DET[Face Detection]
        LAND[Landmark Extraction<br/>936-dim normalized]
        EMB[Embedding Generation]
    end

    subgraph Matching Engine
        COS[Cosine Similarity]
        TOP3[Top-3 Average Scoring]
        THR[Threshold Gate]
    end

    subgraph Registry
        DB[(Face Database)]
        REG[Registration Module]
        PHOTO[Webcam Capture]
    end

    subgraph Output
        AUTH[✅ Authorized]
        DENY[❌ Denied]
        LOG[📝 Event Log]
        API[🔌 REST/gRPC API]
    end

    CAM --> DET
    MULTI --> DET
    DET --> LAND
    LAND --> EMB
    EMB --> COS
    DB --> COS
    COS --> TOP3
    TOP3 --> THR
    THR --> AUTH
    THR --> DENY
    AUTH --> LOG
    DENY --> LOG
    LOG --> API
    PHOTO --> REG
    REG --> DB

