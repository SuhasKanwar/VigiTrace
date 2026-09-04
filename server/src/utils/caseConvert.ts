/**
 * The Python service speaks snake_case; the rest of this server speaks
 * camelCase. Conversion happens only at the vendor boundary.
 *
 * Keys that are not plain identifiers are left verbatim, because vendor
 * payloads use raw endpoint paths ("/ISAPI/System/deviceInfo") and XML
 * attribute markers ("@version") as object keys. Anything nested under a key
 * literally named `raw` is left completely untouched: that is the verbatim
 * vendor evidence and rewriting it would destroy provenance.
 */

const IDENTIFIER = /^[A-Za-z][A-Za-z0-9_]*$/;

function snakeKey(key: string): string {
    if (!IDENTIFIER.test(key)) {
        return key;
    }
    return key.replace(/([a-z0-9])([A-Z])/g, "$1_$2").toLowerCase();
}

function camelKey(key: string): string {
    if (!IDENTIFIER.test(key)) {
        return key;
    }
    return key.replace(/_([a-z0-9])/g, (_match, character: string) => character.toUpperCase());
}

function convert(value: unknown, mapKey: (key: string) => string): unknown {
    if (Array.isArray(value)) {
        return value.map((item) => convert(item, mapKey));
    }
    if (value === null || typeof value !== "object" || value instanceof Date) {
        return value;
    }
    const output: Record<string, unknown> = {};
    for (const [key, item] of Object.entries(value as Record<string, unknown>)) {
        output[mapKey(key)] = key === "raw" ? item : convert(item, mapKey);
    }
    return output;
}

/** Deep-convert an object's keys to snake_case for the Python service. */
export function toSnakeCaseDeep(value: unknown): unknown {
    return convert(value, snakeKey);
}

/** Deep-convert a service payload's keys to camelCase for the client. */
export function toCamelCaseDeep(value: unknown): unknown {
    return convert(value, camelKey);
}
