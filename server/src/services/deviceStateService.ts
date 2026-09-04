import prisma from "../lib/prisma.js";
import { DeviceState } from "../generated/prisma/enums.js";
import { sha256Hex } from "../utils/crypto.js";
import type { Device } from "../generated/prisma/client.js";

/**
 * States that represent forward progress through the acquisition pipeline.
 * Any of them may fail, so every one of them can reach a terminal failure.
 */
const PROGRESS_STATES: DeviceState[] = [
    DeviceState.REGISTERED,
    DeviceState.IDENTIFYING,
    DeviceState.IDENTIFIED,
    DeviceState.ENUMERATING,
    DeviceState.ENUMERATED,
    DeviceState.INDEXING,
    DeviceState.INDEXED,
    DeviceState.ACQUIRING,
    DeviceState.ACQUIRED,
    DeviceState.VERIFYING,
    DeviceState.VERIFIED,
];

/**
 * The four failure states are kept distinguishable so an investigator can tell
 * "wrong password" from "wrong vendor" from "cable unplugged". Each of them is
 * recoverable: a retry sends the device back to REGISTERED or IDENTIFYING.
 */
export const FAILURE_STATES: DeviceState[] = [
    DeviceState.UNREACHABLE,
    DeviceState.AUTH_FAILED,
    DeviceState.UNSUPPORTED,
    DeviceState.FAILED,
];

// Enumeration re-reads channel and storage state, which changes on a live
// recorder as disks fill and fail, so every settled post-identification state
// can re-enter ENUMERATING.
//
// Verification re-hashes artifacts already on disk, which exist independently
// of where the device sits in the probe pipeline: a recorder re-identified
// after an acquisition must still be verifiable. Every settled state therefore
// reaches VERIFYING, and the handler's own "no acquisitions" guard is what
// makes verification meaningful rather than the pipeline position.
const FORWARD_TRANSITIONS: Record<DeviceState, DeviceState[]> = {
    [DeviceState.REGISTERED]: [DeviceState.IDENTIFYING],
    // The in-progress states may re-enter themselves so a run interrupted
    // mid-probe can be retried instead of stranding the device forever.
    [DeviceState.IDENTIFYING]: [DeviceState.IDENTIFYING, DeviceState.IDENTIFIED],
    [DeviceState.IDENTIFIED]: [DeviceState.IDENTIFYING, DeviceState.ENUMERATING, DeviceState.INDEXING, DeviceState.VERIFYING],
    [DeviceState.ENUMERATING]: [DeviceState.ENUMERATING, DeviceState.ENUMERATED],
    [DeviceState.ENUMERATED]: [DeviceState.IDENTIFYING, DeviceState.ENUMERATING, DeviceState.INDEXING, DeviceState.ACQUIRING, DeviceState.VERIFYING],
    [DeviceState.INDEXING]: [DeviceState.INDEXING, DeviceState.INDEXED],
    [DeviceState.INDEXED]: [DeviceState.IDENTIFYING, DeviceState.ENUMERATING, DeviceState.INDEXING, DeviceState.ACQUIRING, DeviceState.VERIFYING],
    [DeviceState.ACQUIRING]: [DeviceState.ACQUIRING, DeviceState.ACQUIRED],
    [DeviceState.ACQUIRED]: [DeviceState.IDENTIFYING, DeviceState.ENUMERATING, DeviceState.INDEXING, DeviceState.ACQUIRING, DeviceState.VERIFYING],
    [DeviceState.VERIFYING]: [DeviceState.VERIFYING, DeviceState.VERIFIED],
    [DeviceState.VERIFIED]: [DeviceState.IDENTIFYING, DeviceState.ENUMERATING, DeviceState.INDEXING, DeviceState.ACQUIRING, DeviceState.VERIFYING],
    [DeviceState.UNREACHABLE]: [],
    [DeviceState.AUTH_FAILED]: [],
    [DeviceState.UNSUPPORTED]: [],
    [DeviceState.FAILED]: [],
};

function buildTransitionMap(): Record<DeviceState, DeviceState[]> {
    const map = {} as Record<DeviceState, DeviceState[]>;
    for (const state of PROGRESS_STATES) {
        map[state] = [...(FORWARD_TRANSITIONS[state] ?? []), ...FAILURE_STATES];
    }
    for (const state of FAILURE_STATES) {
        map[state] = [DeviceState.REGISTERED, DeviceState.IDENTIFYING];
    }
    return map;
}

export const ALLOWED_TRANSITIONS: Record<DeviceState, DeviceState[]> = buildTransitionMap();

export class DeviceStateTransitionError extends Error {
    public readonly from: DeviceState;
    public readonly to: DeviceState;

    constructor(from: DeviceState, to: DeviceState) {
        super(
            `A device in the ${from} state cannot move to ${to}. Allowed next states are: ${(ALLOWED_TRANSITIONS[from] ?? []).join(", ") || "none"}.`
        );
        this.name = "DeviceStateTransitionError";
        this.from = from;
        this.to = to;
    }
}

export function canTransition(from: DeviceState, to: DeviceState): boolean {
    return (ALLOWED_TRANSITIONS[from] ?? []).includes(to);
}

export function isFailureState(state: DeviceState): boolean {
    return FAILURE_STATES.includes(state);
}

/**
 * Compute this custody entry's digest from the previous one, so the chain is
 * verifiable end to end and a removed or edited row is detectable.
 */
function chainDigest(previousDigest: string | null, payload: Record<string, unknown>): string {
    return sha256Hex(`${previousDigest ?? "GENESIS"}|${JSON.stringify(payload)}`);
}

type CustodyWriter = {
    custodyEvent: {
        findFirst: (args: unknown) => Promise<{ digest: string | null } | null>;
        create: (args: unknown) => Promise<unknown>;
    };
};

async function appendCustody(
    tx: CustodyWriter,
    deviceId: string,
    userId: string,
    action: string,
    fromState: DeviceState | null,
    toState: DeviceState | null,
    detail: string | null
): Promise<string> {
    const previous = await tx.custodyEvent.findFirst({
        where: { deviceId },
        orderBy: { createdAt: "desc" },
        select: { digest: true },
    });
    const digest = chainDigest(previous?.digest ?? null, {
        deviceId,
        userId,
        action,
        fromState,
        toState,
        detail,
    });
    await tx.custodyEvent.create({
        data: {
            deviceId,
            userId,
            action,
            fromState,
            toState,
            detail,
            digest,
        },
    });
    return digest;
}

/**
 * Record a custody entry that is not itself a state change (registration,
 * credential rotation, an unauthenticated detection run, deletion).
 */
export async function recordCustodyEvent(
    deviceId: string,
    userId: string,
    action: string,
    detail?: string | null
): Promise<string> {
    return prisma.$transaction(async (tx) =>
        appendCustody(tx as unknown as CustodyWriter, deviceId, userId, action, null, null, detail ?? null)
    );
}

/**
 * Move a device to a new state and append the matching chain-of-custody entry
 * in one transaction, so a state can never change without a custody record.
 */
export async function transitionDevice(
    deviceId: string,
    userId: string,
    toState: DeviceState,
    detail?: string | null,
    action = "STATE_TRANSITION"
): Promise<Device> {
    return prisma.$transaction(async (tx) => {
        const device = await tx.device.findFirst({
            where: { id: deviceId, userId },
            select: { id: true, state: true },
        });
        if (!device) {
            throw new Error("Device not found for this user.");
        }
        if (!canTransition(device.state, toState)) {
            throw new DeviceStateTransitionError(device.state, toState);
        }

        await appendCustody(
            tx as unknown as CustodyWriter,
            deviceId,
            userId,
            action,
            device.state,
            toState,
            detail ?? null
        );

        return tx.device.update({
            where: { id: deviceId },
            data: { state: toState },
        });
    });
}
