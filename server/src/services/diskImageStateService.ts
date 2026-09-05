import prisma from "../lib/prisma.js";
import { DiskImageState } from "../generated/prisma/enums.js";
import { sha256Hex } from "../utils/crypto.js";
import type { DiskImage } from "../generated/prisma/client.js";

/**
 * A disk image's state machine is far smaller than a live Device's: there is
 * no network round trip to retry mid-flight, only "has this image been
 * analysed yet, and did that analysis succeed". Analysis is idempotent
 * (children are upserted), so every settled state - including ANALYSED - can
 * re-enter ANALYSING to support a deliberate re-run.
 */
const FORWARD_TRANSITIONS: Record<DiskImageState, DiskImageState[]> = {
    [DiskImageState.REGISTERED]: [DiskImageState.ANALYSING],
    [DiskImageState.ANALYSING]: [
        DiskImageState.ANALYSING,
        DiskImageState.ANALYSED,
        DiskImageState.UNSUPPORTED,
        DiskImageState.FAILED,
    ],
    [DiskImageState.ANALYSED]: [DiskImageState.ANALYSING],
    [DiskImageState.UNSUPPORTED]: [DiskImageState.ANALYSING],
    [DiskImageState.FAILED]: [DiskImageState.ANALYSING],
};

export class DiskImageStateTransitionError extends Error {
    public readonly from: DiskImageState;
    public readonly to: DiskImageState;

    constructor(from: DiskImageState, to: DiskImageState) {
        super(
            `A disk image in the ${from} state cannot move to ${to}. Allowed next states are: ${(FORWARD_TRANSITIONS[from] ?? []).join(", ") || "none"}.`
        );
        this.name = "DiskImageStateTransitionError";
        this.from = from;
        this.to = to;
    }
}

export function canTransitionDiskImage(from: DiskImageState, to: DiskImageState): boolean {
    return (FORWARD_TRANSITIONS[from] ?? []).includes(to);
}

/**
 * Compute this event's digest from the previous one, so the chain is
 * verifiable end to end and a removed or edited row is detectable. Same
 * construction as the Device chain of custody, applied to disk images.
 */
function chainDigest(previousDigest: string | null, payload: Record<string, unknown>): string {
    return sha256Hex(`${previousDigest ?? "GENESIS"}|${JSON.stringify(payload)}`);
}

type EventWriter = {
    diskImageEvent: {
        findFirst: (args: unknown) => Promise<{ digest: string | null } | null>;
        create: (args: unknown) => Promise<unknown>;
    };
};

async function appendEvent(
    tx: EventWriter,
    diskImageId: string,
    userId: string,
    action: string,
    fromState: DiskImageState | null,
    toState: DiskImageState | null,
    detail: string | null
): Promise<string> {
    const previous = await tx.diskImageEvent.findFirst({
        where: { diskImageId },
        orderBy: { createdAt: "desc" },
        select: { digest: true },
    });
    const digest = chainDigest(previous?.digest ?? null, {
        diskImageId,
        userId,
        action,
        fromState,
        toState,
        detail,
    });
    await tx.diskImageEvent.create({
        data: {
            diskImageId,
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
 * Record an event that is not itself a state change (registration,
 * deletion, a rejected registration attempt logged before any row existed).
 */
export async function recordDiskImageEvent(
    diskImageId: string,
    userId: string,
    action: string,
    detail?: string | null
): Promise<string> {
    return prisma.$transaction(async (tx) =>
        appendEvent(tx as unknown as EventWriter, diskImageId, userId, action, null, null, detail ?? null)
    );
}

/**
 * Move a disk image to a new state and append the matching audit entry in one
 * transaction, so a state can never change without a record of why.
 */
export async function transitionDiskImage(
    diskImageId: string,
    userId: string,
    toState: DiskImageState,
    detail?: string | null,
    action = "STATE_TRANSITION"
): Promise<DiskImage> {
    return prisma.$transaction(async (tx) => {
        const image = await tx.diskImage.findFirst({
            where: { id: diskImageId, userId },
            select: { id: true, state: true },
        });
        if (!image) {
            throw new Error("Disk image not found for this user.");
        }
        if (!canTransitionDiskImage(image.state, toState)) {
            throw new DiskImageStateTransitionError(image.state, toState);
        }

        await appendEvent(
            tx as unknown as EventWriter,
            diskImageId,
            userId,
            action,
            image.state,
            toState,
            detail ?? null
        );

        return tx.diskImage.update({
            where: { id: diskImageId },
            data: { state: toState },
        });
    });
}
