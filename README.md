# VigiTrace

## Multi-vendor DVR/NVR forensic analysis

VigiTrace is a proposed vendor-agnostic platform for standardized acquisition, recovery, validation, analysis, and reporting of surveillance evidence. It is designed for investigators, digital-forensics teams, law-enforcement agencies, critical-infrastructure operators, and organizations that need a defensible record of what happened on a DVR/NVR system.

Surveillance evidence is difficult to handle consistently because each recorder manufacturer can use a different storage layout, filesystem, metadata model, timestamp convention, and video encoding. VigiTrace brings those workflows into one evidence-first case model so acquisition decisions, recovered media, analysis results, integrity checks, and chain-of-custody events can be reviewed together.

> Current status: the repository contains a working web prototype, an authentication foundation, and a functional multi-vendor **network** acquisition pipeline (device identification, channel/storage enumeration, recording-index search, controlled export with integrity hashing, and rule-based analysis) for Hikvision, Dahua, CP Plus, and Godrej recorders.
>
> Forensic disk imaging, proprietary on-disk filesystem parsing (HIKBTREE, DHFS 4.1), and deleted-footage recovery are **not** implemented. Nothing here has been validated against physical recorder hardware, and no capability is production-certified.

## Why this project exists

Investigators commonly switch between vendor-specific utilities and media players. That creates avoidable problems:

- non-standard acquisition procedures and incomplete device identification;
- proprietary filesystems, containers, codecs, and metadata structures;
- damaged, fragmented, or deleted recordings that ordinary playback cannot recover;
- inconsistent recorder clocks and timezone handling;
- weak correlation of events across cameras and locations;
- incomplete chain-of-custody records and difficult evidence validation;
- duplicated work across multiple tools and inconsistent reports.

VigiTrace aims to provide one repeatable workflow that preserves original source context while making recovered footage and findings easier to review, verify, and explain.

## Product goals

The target platform will support DVR/NVR systems from major OEM families including Dahua Technology, CP Plus, Honeywell Security, TP-Link, Godrej, Uniview, Hikvision, Matrix, and other commonly encountered platforms. A device adapter should translate manufacturer-specific formats into a common evidence model without hiding original metadata.

The planned workflow is:

1. **Identify** — detect recorder model, firmware, channels, storage layout, clock state, and connected media.
2. **Acquire** — create a defensible forensic image or controlled export while recording operator actions and source details.
3. **Parse** — inspect proprietary filesystems, containers, indexes, metadata, and codecs through vendor adapters.
4. **Recover** — locate deleted, fragmented, damaged, or otherwise unindexed recordings and preserve provenance.
5. **Normalize** — reconcile timestamps, timezone offsets, camera identifiers, and event boundaries into one timeline.
6. **Analyze** — correlate cameras and events and optionally use face, object, and motion detection as investigator-assistance signals.
7. **Validate and report** — calculate MD5 and SHA-256 hashes, maintain chain of custody, and produce a standardized report.

## Planned modules

| Module | Purpose |
| --- | --- |
| Device Identification | Identify OEM, model, firmware, channels, storage, and acquisition constraints. |
| Acquisition | Capture source media, forensic images, exports, operator actions, and acquisition notes. |
| Filesystem and Format Parsing | Decode vendor-specific layouts, indexes, metadata, containers, and codecs. |
| Recovery | Recover deleted, damaged, fragmented, or unindexed recordings with provenance. |
| Timeline Analysis | Normalize time and correlate events across cameras and sites. |
| Integrity and Chain of Custody | Generate hashes and preserve attributable evidence handoffs. |
| Reporting | Produce repeatable case summaries, technical details, findings, and validation records. |
| Machine Learning | Surface possible faces, objects, and motion for human review; never replace source evidence. |

## Vendor support

Vendor coverage is organised by **protocol lineage**, not by brand, because several badges share one
firmware stack. Getting this mapping wrong sends the whole downstream pipeline to the wrong parser,
so each adapter records the evidence its attribution rests on.

| Vendor | Family | Transport | Confidence | Basis |
| --- | --- | --- | --- | --- |
| Hikvision | HIKVISION | ISAPI over HTTP digest (80/443) | Confirmed | Vendor-published ISAPI developer guide |
| Dahua | DAHUA | HTTP CGI over digest (80/443) | Confirmed | Vendor-published HTTP API specification |
| CP Plus | DAHUA | HTTP CGI over digest, ONVIF Profile G | Probable | CP Plus firmware is Dahua-derived (see below) |
| Godrej | XIONGMAI | DVRIP binary on TCP 34567 | Probable | Device fingerprints indicate XiongMai white-label hardware |

**CP Plus is handled by the Dahua adapter rather than a copy of it.** CP Plus SmartPlayer binaries
export Dahua C++ symbols (`Dahua::StreamPackage::CFlvPacket::InputData`), ship a `DAV Video
File(*.dav)` filter, and CP Plus firmware advisories carry Dahua's own version convention
(`V4.001.00AT009.0.R`). CP Plus publishes no acknowledgement of this, so the relationship is inferred
from artifacts and the adapter reports `PROBABLE` rather than `CONFIRMED`.

**Godrej is the weakest link and is labelled as such.** Godrej Security Solutions publishes no SDK,
no API documentation and holds no ONVIF conformance. Attribution to XiongMai rests on device
fingerprints (DVRIP on TCP 34567, the `192.168.1.10` default address, the admin/guest default pair).
The adapter therefore declares only four capabilities and never claims better than `PROBABLE`
confidence. A Godrej unit from a different hardware generation may not answer DVRIP at all; that is
reported as `UNSUPPORTED` with the observed fingerprint attached, not silently mis-parsed.

### Why no vendor SDKs

Neither Hikvision's HCNetSDK nor Dahua's NetSDK is used, and neither is a dependency. The HIKVISION
Materials License Agreement forbids distributing any portion of the SDK or permitting it "to be
combined with, or become incorporated in, any other products or programs", and Dahua's licence
forbids decomposing the software or embedding parts of it into another system. Both are closed-source
binaries behind account registration.

Every adapter is therefore a clean-room implementation over published network protocols. The GPL-2.0
`amcrest` package covers similar Dahua ground but its copyleft would be viral for a distributable
forensics tool, so the CGI surface is implemented directly. Note also that the PyPI name `dahua`
belongs to an unrelated package and must not be installed.

## Repository status

Implemented in the current prototype:

- Next.js client with a Cloudflare-inspired light visual system using centralized CSS variables;
- responsive landing page with workflow storytelling, evidence network visualization, and integrity sections;
- Three.js globe with country boundaries, evidence nodes, and animated coordinate-to-coordinate routes;
- shared VigiTrace wordmark component, status screens, loading state, and footer;
- NextAuth credentials and Google provider integration;
- Express authentication API for sign-up, sign-in, Google account confirmation, and sign-out;
- PostgreSQL/Prisma `User` model with credentials and Google provider metadata;
- JWT creation and bearer/cookie authentication middleware;
- vendor adapters for Hikvision (ISAPI), Dahua (HTTP CGI), CP Plus (Dahua lineage) and Godrej (DVRIP);
- unauthenticated vendor fingerprinting that explains which signals produced its verdict;
- a standardized device model carrying verbatim vendor payloads and per-response SHA-256 digests;
- recording-index search with gap detection, and clock-drift-corrected timeline normalization;
- controlled export with MD5/SHA-256 computed on the stream as it is written;
- a guarded device state machine with an append-only chain-of-custody record;
- rule-based analysis findings that work with no AI credentials configured.

Not yet implemented or validated against physical recorder hardware:

- **forensic disk imaging, write-blocker integration, and on-disk filesystem parsing** — the pipeline
  currently acquires over the network from a live recorder, not from a disk image;
- proprietary codec decoding and deleted-file recovery from unallocated blocks;
- production ML inference, benchmark results, and admissibility certification;
- deployment, backup/restore, scale, and hardware soak testing.

Every adapter has been exercised against protocol-accurate mock recorders. **None has been tested
against physical hardware**, which remains the single most important outstanding validation step.

## Architecture

```text
Browser (Next.js / React / Three.js)          :3000
        │
        ├── NextAuth session and provider callbacks
        │
        ▼
Express API (CORS, JSON, cookies, logging)    :9000
        │
        ├── Authentication handlers
        ├── JWT and cookie middleware
        ├── Device lifecycle + chain of custody
        └── PostgreSQL via Prisma  ◄── the only component that touches the database
        │
        ▼
FastAPI forensic service                      :8000
        │
        ├── Vendor detection (unauthenticated fingerprinting)
        ├── Vendor adapters (Hikvision / Dahua / CP Plus / Godrej)
        ├── Recording index, normalization, acquisition
        └── Rule-based analysis  ◄── stateless; stores nothing, persists nothing
```

Three rules hold this together:

1. **The browser never calls the forensic service.** The Express API is the only proxy.
2. **All persistence lives in the server.** The Python service is stateless and never receives a database handle; credentials reach it per-request and are not retained.
3. **Adapters normalize without discarding.** Every standardized object carries the verbatim vendor payload and a SHA-256 of each retained response, so normalization never destroys provenance.

The client lives in `client/`, the API and persistence layer in `server/`, and the vendor/forensic processing in `service/`. Generated Prisma client files are under `server/src/generated/prisma`.

## Project structure

```text
v1/
├── client/
│   └── src/
│       ├── app/                 # Next.js routes, auth pages, dashboard, API callback
│       ├── components/          # Auth, home, globe, logo, status, and toast UI
│       ├── context/             # Session and toast providers
│       ├── data/                # Globe country boundary data
│       ├── lib/                 # API, session, config, and toast helpers
│       └── types/               # NextAuth type augmentation
├── server/
│   ├── prisma/                  # Schema and migrations
│   └── src/                     # Express app, routes, controllers, middleware, utilities
└── service/
    ├── models/                  # Pydantic evidence models (the standardized object)
    ├── vendors/
    │   ├── base.py              # Adapter contract and capability declarations
    │   ├── registry.py          # Adapter registry and vendor detection
    │   ├── transports/          # HTTP digest and DVRIP wire protocols
    │   ├── hikvision.py         # ISAPI
    │   ├── dahua.py             # HTTP CGI (family base)
    │   ├── cpplus.py            # Dahua lineage
    │   └── godrej.py            # XiongMai DVRIP
    ├── services/                # Probe orchestration, normalization, integrity
    ├── routers/                 # FastAPI route modules
    └── tests/                   # Mock recorders and the adapter test suite
```

## Local development

### Requirements

- Node.js 20 or newer;
- npm;
- PostgreSQL for the server database;
- Google OAuth credentials if Google sign-in is enabled.

### Install

```bash
cd server && npm install
cd ../client && npm install
cd ../service && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

The service needs Python 3.10 or newer; it is developed against 3.14.

Copy the environment templates and set values for the local machine:

```bash
cp server/.env.example server/.env
cp client/.env.example client/.env
cp service/.env.example service/.env
```

At minimum, configure `DATABASE_URL`, `JWT_SECRET`, `NEXTAUTH_SECRET`, and the client/server URLs. Use long, unique secrets outside local development.

### Database and services

```bash
cd server
npm run db:generate
npm run db:migrate
npm run dev
```

In a second terminal:

```bash
cd client
npm run dev
```

In a third terminal:

```bash
cd service
.venv/bin/python app.py
```

The client runs at `http://localhost:3000`, the API at `http://localhost:9000`, and the forensic
service at `http://localhost:8000` (interactive API docs at `/docs`).

The service must be running for any device operation to work; the server surfaces a clear
"service unavailable" message rather than failing opaquely when it is not.

Useful checks:

```bash
cd client && npm run build && npm run lint
cd server && npm run build
cd service && .venv/bin/python -m pytest
```

## Authentication API

| Method | Endpoint | Description |
| --- | --- | --- |
| `POST` | `/api/auth/signup` | Create a credentials-based user and issue a JWT cookie. |
| `POST` | `/api/auth/signin` | Verify credentials and return the authenticated user and token. |
| `POST` | `/api/auth/google` | Create or confirm a Google-backed user. |
| `POST` | `/api/auth/signout` | Clear the authorization cookie. |
| `GET` | `/health` | Return server health status. |

The client uses NextAuth as the session boundary. Credentials are forwarded to the Express API, while Google callbacks confirm the account with the API before the session token is populated.

## Device API

All device routes require authentication and are scoped to the calling user. Every response uses the
standard `{ success, message, data?, error? }` envelope.

| Method | Endpoint | Description |
| --- | --- | --- |
| `GET` | `/api/devices/vendors` | List registered vendor adapters and their capabilities. |
| `POST` | `/api/devices` | Register a recorder. Credentials are encrypted at rest. |
| `GET` | `/api/devices` | List the caller's registered recorders. |
| `GET` | `/api/devices/:id` | One recorder with channels, storage, latest probe, and custody tail. |
| `PATCH` | `/api/devices/:id` | Update recorder details or credentials. |
| `DELETE` | `/api/devices/:id` | Remove a recorder and its dependent records. |
| `POST` | `/api/devices/:id/detect` | Fingerprint the recorder without authenticating. |
| `POST` | `/api/devices/:id/identify` | Full identification into the standardized evidence model. |
| `POST` | `/api/devices/:id/recordings/search` | Search the recorder's own recording index. |
| `GET` | `/api/devices/:id/recordings` | List persisted recording-index entries. |
| `POST` | `/api/devices/:id/acquisitions` | Controlled export with MD5/SHA-256 integrity hashes. |
| `GET` | `/api/devices/:id/acquisitions` | List completed acquisitions. |
| `GET` | `/api/devices/:id/custody` | Append-only chain-of-custody record. |
| `POST` | `/api/devices/:id/analysis` | Rule-based findings for investigator review. |

### Device lifecycle

State transitions are guarded, and every transition writes a chain-of-custody event in the same
database transaction as the state change:

```text
REGISTERED → IDENTIFYING → IDENTIFIED → ENUMERATING → ENUMERATED
           → INDEXING → INDEXED → ACQUIRING → ACQUIRED → VERIFYING → VERIFIED
```

Four terminal failure states are distinguishable so an investigator can tell a wrong password from a
wrong vendor from an unplugged cable: `UNREACHABLE`, `AUTH_FAILED`, `UNSUPPORTED`, `FAILED`.

## Evidence integrity and safety principles

The target forensic workflow must preserve original media, record acquisition context, keep derived artifacts separate from source evidence, and make every transformation attributable. Hashes and reports are validation aids; they do not by themselves prove that a physical acquisition was performed correctly. Hardware-level claims require testing with representative DVR/NVR devices, write protection, clock drift, damaged media, and documented repeatability.

## Deliverables and roadmap

Planned deliverables include comparative OEM and storage-format analysis, system architecture and adapter contracts, a DVR/NVR forensic image workflow, a functional acquisition/recovery/analysis/reporting prototype, standard operating procedures, validation reports, a user manual, and a final project report.

The next implementation slices should establish a case/evidence schema, define the vendor-adapter contract, add fixture-based parser tests, and validate one OEM end-to-end before expanding support or AI-assisted analysis.

## License and project ownership

This project is maintained by NullPointers. Licensing and contribution terms should be finalized before external distribution.
