import dotenv from "dotenv";

dotenv.config();

export const PORT: number = Number(process.env.PORT) || 9000;
export const NODE_ENV: string = process.env.NODE_ENV || "development";
export const DATABASE_URL: string = process.env.DATABASE_URL || "postgresql://postgres:dev@localhost:5432/cloudcanvas";
export const MICROSERVICE_BASE_URL: string = process.env.MICROSERVICE_BASE_URL || "http://localhost:8000";
export const JWT_SECRET: string = process.env.JWT_SECRET || "secret";
export const JWT_EXPIRES_IN: string = process.env.JWT_EXPIRES_IN || "7d";
export const LOGS_DIRECTORY: string = "logs";

const FRONTED_URL: string = process.env.FRONTED_URL || "http://localhost:3000"
export const ALLOWED_ORIGINS: string[] = [FRONTED_URL];

export const MICROSERVICE_TIMEOUT_MS: number = Number(process.env.MICROSERVICE_TIMEOUT_MS) || 30_000;
export const MICROSERVICE_ACQUIRE_TIMEOUT_MS: number = Number(process.env.MICROSERVICE_ACQUIRE_TIMEOUT_MS) || 300_000;
// Analysis may wait on an optional LLM narration whose own worst case is ~25s
// when the upstream is throttling. The default 30s budget cut that off and
// turned a degraded narration into a 504 that discarded findings the service
// had already computed, so this stage gets its own, larger allowance.
export const MICROSERVICE_ANALYSIS_TIMEOUT_MS: number = Number(process.env.MICROSERVICE_ANALYSIS_TIMEOUT_MS) || 60_000;
export const VENDOR_REGISTRY_CACHE_TTL_SECONDS: number = Number(process.env.VENDOR_REGISTRY_CACHE_TTL_SECONDS) || 3600;

/**
 * AES-256-GCM key used to encrypt recorder credentials at rest. Recorder
 * passwords are the keys to somebody else's evidence, so a missing key is a
 * startup failure rather than a silent fallback to plaintext.
 */
function readCredentialEncryptionKey(): Buffer {
    const raw = process.env.CREDENTIAL_ENCRYPTION_KEY;
    if (!raw) {
        throw new Error(
            "CREDENTIAL_ENCRYPTION_KEY is not set. Generate one with `node -e \"console.log(require('crypto').randomBytes(32).toString('hex'))\"` and add it to .env before starting the server."
        );
    }
    if (!/^[0-9a-fA-F]{64}$/.test(raw.trim())) {
        throw new Error(
            "CREDENTIAL_ENCRYPTION_KEY must be exactly 32 bytes encoded as 64 hexadecimal characters."
        );
    }
    return Buffer.from(raw.trim(), "hex");
}

export const CREDENTIAL_ENCRYPTION_KEY: Buffer = readCredentialEncryptionKey();
