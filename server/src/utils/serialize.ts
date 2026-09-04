/**
 * `JSON.stringify` throws on `bigint`, and Prisma hands back real bigints for
 * every byte-count column. A 2 TB disk capacity must not be able to crash a
 * response, so every payload that can carry one is passed through here first.
 *
 * Bigints become decimal strings rather than numbers: a byte count can exceed
 * `Number.MAX_SAFE_INTEGER`, and silently losing precision on evidence sizes is
 * worse than making the client parse a string.
 */
export function toSerializable<T>(value: T): unknown {
    if (typeof value === "bigint") {
        return value.toString();
    }
    if (value === null || typeof value !== "object") {
        return value;
    }
    if (value instanceof Date) {
        return value.toISOString();
    }
    if (Buffer.isBuffer(value)) {
        return value.toString("base64");
    }
    if (Array.isArray(value)) {
        return value.map((item) => toSerializable(item));
    }
    const output: Record<string, unknown> = {};
    for (const [key, item] of Object.entries(value as Record<string, unknown>)) {
        output[key] = toSerializable(item);
    }
    return output;
}

/** Parse a value that may arrive as a number, a bigint or a decimal string. */
export function toBigIntOrNull(value: unknown): bigint | null {
    if (value === null || value === undefined || value === "") {
        return null;
    }
    if (typeof value === "bigint") {
        return value;
    }
    if (typeof value === "number") {
        return Number.isFinite(value) ? BigInt(Math.trunc(value)) : null;
    }
    if (typeof value === "string" && /^-?\d+$/.test(value.trim())) {
        return BigInt(value.trim());
    }
    return null;
}
