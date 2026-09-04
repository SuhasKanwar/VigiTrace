import crypto from "node:crypto";
import { CREDENTIAL_ENCRYPTION_KEY } from "../lib/config.js";

const ALGORITHM = "aes-256-gcm";
const IV_LENGTH = 12;
const AUTH_TAG_LENGTH = 16;

/**
 * Encrypt a recorder credential for storage.
 *
 * The stored form is `iv:authTag:ciphertext`, all hex. The auth tag is kept
 * separately so a tampered ciphertext fails to decrypt loudly rather than
 * yielding garbage that would be sent to a live recorder.
 */
export function encryptSecret(plaintext: string): string {
    const iv = crypto.randomBytes(IV_LENGTH);
    const cipher = crypto.createCipheriv(ALGORITHM, CREDENTIAL_ENCRYPTION_KEY, iv, {
        authTagLength: AUTH_TAG_LENGTH,
    });
    const ciphertext = Buffer.concat([cipher.update(plaintext, "utf8"), cipher.final()]);
    const authTag = cipher.getAuthTag();
    return `${iv.toString("hex")}:${authTag.toString("hex")}:${ciphertext.toString("hex")}`;
}

/** Decrypt a value produced by {@link encryptSecret}. */
export function decryptSecret(payload: string): string {
    const parts = payload.split(":");
    if (parts.length !== 3) {
        throw new Error("Stored credential is not in the expected iv:authTag:ciphertext format.");
    }
    const [ivHex, authTagHex, ciphertextHex] = parts as [string, string, string];
    const iv = Buffer.from(ivHex, "hex");
    const authTag = Buffer.from(authTagHex, "hex");
    const ciphertext = Buffer.from(ciphertextHex, "hex");
    if (iv.length !== IV_LENGTH || authTag.length !== AUTH_TAG_LENGTH) {
        throw new Error("Stored credential has a malformed initialisation vector or authentication tag.");
    }
    const decipher = crypto.createDecipheriv(ALGORITHM, CREDENTIAL_ENCRYPTION_KEY, iv, {
        authTagLength: AUTH_TAG_LENGTH,
    });
    decipher.setAuthTag(authTag);
    return Buffer.concat([decipher.update(ciphertext), decipher.final()]).toString("utf8");
}

/** True when a stored string looks like ciphertext this module produced. */
export function isEncryptedSecret(value: string): boolean {
    const parts = value.split(":");
    if (parts.length !== 3) {
        return false;
    }
    return parts.every((part) => /^[0-9a-f]*$/i.test(part) && part.length > 0);
}

/** Stable SHA-256 digest, used for chain-of-custody entries. */
export function sha256Hex(value: string): string {
    return crypto.createHash("sha256").update(value, "utf8").digest("hex");
}
