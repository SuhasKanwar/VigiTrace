# VigiTrace

## Multi-vendor DVR/NVR forensic analysis

VigiTrace is a proposed vendor-agnostic platform for standardized acquisition, recovery, validation, analysis, and reporting of surveillance evidence. It is designed for investigators, digital-forensics teams, law-enforcement agencies, critical-infrastructure operators, and organizations that need a defensible record of what happened on a DVR/NVR system.

Surveillance evidence is difficult to handle consistently because each recorder manufacturer can use a different storage layout, filesystem, metadata model, timestamp convention, and video encoding. VigiTrace brings those workflows into one evidence-first case model so acquisition decisions, recovered media, analysis results, integrity checks, and chain-of-custody events can be reviewed together.

> Current status: the repository contains a working web prototype and authentication foundation. Vendor filesystem parsing, forensic imaging, deleted-footage recovery, and machine-learning pipelines are planned modules—not yet production-certified capabilities.

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
- protected `/dashboard` route reserved for the case workspace.

Not yet implemented or validated against physical recorder hardware:

- OEM filesystem adapters and automatic recorder identification;
- forensic disk imaging and write-blocker integration;
- proprietary codec decoding and deleted-file recovery;
- evidence/case persistence beyond the initial user model;
- production ML inference, benchmark results, and admissibility certification;
- deployment, backup/restore, scale, and hardware soak testing.

## Architecture

```text
Browser (Next.js / React / Three.js)
        │
        ├── NextAuth session and provider callbacks
        │
        └── Express API (CORS, JSON, cookies, logging)
                │
                ├── Authentication handlers
                ├── JWT and cookie middleware
                └── PostgreSQL via Prisma
```

The client lives in `client/`. The API and persistence layer live in `server/`. The `service/` directory is reserved for future forensic processing services. Generated Prisma client files are under `server/src/generated/prisma`.

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
└── service/                     # Reserved processing-service workspace
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
```

Copy the environment templates and set values for the local machine:

```bash
cp server/.env.example server/.env
cp client/.env.example client/.env
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

The client runs at `http://localhost:3000`; the API defaults to `http://localhost:9000`.

Useful checks:

```bash
cd client && npm run build && npm run lint
cd server && npm run build
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

## Evidence integrity and safety principles

The target forensic workflow must preserve original media, record acquisition context, keep derived artifacts separate from source evidence, and make every transformation attributable. Hashes and reports are validation aids; they do not by themselves prove that a physical acquisition was performed correctly. Hardware-level claims require testing with representative DVR/NVR devices, write protection, clock drift, damaged media, and documented repeatability.

## Deliverables and roadmap

Planned deliverables include comparative OEM and storage-format analysis, system architecture and adapter contracts, a DVR/NVR forensic image workflow, a functional acquisition/recovery/analysis/reporting prototype, standard operating procedures, validation reports, a user manual, and a final project report.

The next implementation slices should establish a case/evidence schema, define the vendor-adapter contract, add fixture-based parser tests, and validate one OEM end-to-end before expanding support or AI-assisted analysis.

## License and project ownership

This project is maintained by NullPointers. Licensing and contribution terms should be finalized before external distribution.
