import { basename, isAbsolute } from "node:path";
import type { Request, Response } from "express";
import prisma from "../lib/prisma.js";
import { DiskImageState } from "../generated/prisma/enums.js";
import type { DiskImage } from "../generated/prisma/client.js";
import type { ApiResponse } from "../types/response.js";
import type { ServiceDiskIdentifyData, ServiceVolumeEvidence } from "../types/vendor.js";
import {
    analyseDiskImage,
    diskStateForServiceError,
    identifyDiskImage,
    type VendorCall,
} from "../services/vendorService.js";
import {
    DiskImageStateTransitionError,
    recordDiskImageEvent,
    transitionDiskImage,
} from "../services/diskImageStateService.js";
import { toCamelCaseDeep } from "../utils/caseConvert.js";
import { toBigIntOrNull, toSerializable } from "../utils/serialize.js";
import { toFamilyEnum, toVendorEnum } from "../utils/device.js";
import { DeviceVendor } from "../generated/prisma/enums.js";

const EVENT_TAIL_SIZE = 25;

type VendorFailure = Extract<VendorCall, { ok: false }>;

function vendorFailureResponse(res: Response<ApiResponse>, call: VendorFailure) {
    return res.status(call.status).json({
        success: false,
        message: call.message,
        error: {
            code: call.code,
            detail: call.detail,
            remediation: call.remediation,
        },
    });
}

/** Express 5 types a route parameter as string | string[]; an image id is a single value. */
function diskImageIdFrom(req: Request): string {
    const value = req.params["id"];
    return typeof value === "string" ? value : "";
}

function unauthorized(res: Response<ApiResponse>) {
    return res.status(401).json({
        success: false,
        message: "Authentication is required to work with disk images.",
    });
}

function notFound(res: Response<ApiResponse>) {
    return res.status(404).json({
        success: false,
        message: "That disk image does not exist, or it does not belong to you.",
    });
}

/** Every disk image read is scoped to the caller: one user never sees another's evidence. */
async function findOwnedDiskImage(userId: string, diskImageId: string): Promise<DiskImage | null> {
    return prisma.diskImage.findFirst({ where: { id: diskImageId, userId } });
}

function transitionFailureResponse(res: Response<ApiResponse>, error: unknown) {
    if (error instanceof DiskImageStateTransitionError) {
        return res.status(409).json({
            success: false,
            message: error.message,
            error: { from: error.from, to: error.to },
        });
    }
    return null;
}

/** Move a disk image into a terminal failure state without masking the original error. */
async function markDiskImageFailed(
    diskImageId: string,
    userId: string,
    code: string,
    detail: string
): Promise<void> {
    try {
        await transitionDiskImage(diskImageId, userId, diskStateForServiceError(code), detail, "ANALYSIS_FAILED");
    } catch (error) {
        console.error("Could not record the failure state for disk image", diskImageId, error);
    }
}

/** Parse a service timestamp, tolerating null and unparsable values. */
function toDate(value: string | null | undefined): Date | null {
    if (!value) {
        return null;
    }
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? null : parsed;
}

/**
 * Load a disk image as ONE complete resource: its recordings, recovered
 * blocks, carved artifacts and audit tail live inside the image object rather
 * than beside it, matching how a Device is returned as a single resource.
 */
async function loadDiskImageResource(userId: string, diskImageId: string) {
    const image = await prisma.diskImage.findFirst({
        where: { id: diskImageId, userId },
        include: {
            recordings: { orderBy: [{ channel: "asc" }, { dataOffset: "asc" }] },
            recoveredBlocks: { orderBy: { blockIndex: "asc" } },
            artifacts: { orderBy: [{ channel: "asc" }, { dataOffset: "asc" }] },
            events: { orderBy: { createdAt: "desc" }, take: EVENT_TAIL_SIZE },
            _count: {
                select: { recordings: true, recoveredBlocks: true, artifacts: true, events: true },
            },
        },
    });

    if (!image) {
        return null;
    }

    const { recordings, recoveredBlocks, artifacts, events, _count, ...rest } = image;
    return {
        ...rest,
        recordings,
        recoveredBlocks,
        artifacts,
        custody: [...events].reverse(),
        counts: _count,
    };
}

/**
 * Persist a VolumeEvidence: the image's own identity fields are updated, and
 * its recordings, recovered blocks and carved artifacts are upserted keyed on
 * each row's natural identity within the volume, so re-analysing the same
 * image never duplicates a row.
 */
async function persistVolumeEvidence(diskImageId: string, evidence: ServiceVolumeEvidence): Promise<void> {
    await prisma.$transaction(async (tx) => {
        await tx.diskImage.update({
            where: { id: diskImageId },
            data: {
                sizeBytes: toBigIntOrNull(evidence.image_size_bytes),
                sha256: evidence.image_sha256 ?? null,
                vendor: toVendorEnum(evidence.identity.vendor),
                family: toFamilyEnum(evidence.identity.family),
                formatVersion: evidence.identity.format_version ?? null,
                examinedAt: toDate(evidence.examined_at),
            },
        });

        for (const recording of evidence.recordings) {
            const dataOffset = toBigIntOrNull(recording.data_offset) ?? BigInt(0);
            const values = {
                channel: recording.channel,
                startTime: toDate(recording.start),
                endTime: toDate(recording.end),
                durationSeconds: recording.duration_seconds ?? null,
                unfinalised: recording.unfinalised,
            };
            await tx.diskRecording.upsert({
                where: { diskImageId_dataOffset: { diskImageId, dataOffset } },
                create: { diskImageId, dataOffset, ...values },
                update: values,
            });
        }

        for (const block of evidence.recovered_blocks) {
            const values = {
                dataOffset: toBigIntOrNull(block.data_offset) ?? BigInt(0),
                packHeaders: block.pack_headers,
                keyframeBoundaries: block.keyframe_boundaries,
                channel: block.channel ?? null,
                timestamp: toDate(block.timestamp),
                confidence: block.confidence,
            };
            await tx.recoveredBlock.upsert({
                where: { diskImageId_blockIndex: { diskImageId, blockIndex: block.block_index } },
                create: { diskImageId, blockIndex: block.block_index, ...values },
                update: values,
            });
        }

        for (const artifact of evidence.artifacts) {
            const values = {
                channel: artifact.channel,
                dataOffset: toBigIntOrNull(artifact.data_offset) ?? BigInt(0),
                sizeBytes: toBigIntOrNull(artifact.size_bytes) ?? BigInt(0),
                sha256: artifact.sha256,
                keyframeAligned: artifact.keyframe_aligned,
                source: artifact.source,
                decoded: artifact.decoded,
                codec: artifact.codec ?? null,
                width: artifact.width ?? null,
                height: artifact.height ?? null,
                frames: artifact.frames ?? null,
                decodeReason: artifact.decode_reason ?? null,
            };
            await tx.carvedArtifact.upsert({
                where: { diskImageId_storedPath: { diskImageId, storedPath: artifact.stored_path } },
                create: { diskImageId, storedPath: artifact.stored_path, ...values },
                update: values,
            });
        }
    });
}

export async function createDiskImageHandler(req: Request, res: Response<ApiResponse>) {
    try {
        const userId = req.userId;
        if (!userId) {
            return unauthorized(res);
        }

        const path = typeof req.body?.path === "string" ? req.body.path.trim() : "";
        if (!path) {
            return res.status(400).json({
                success: false,
                message: "An absolute path to the acquired image is required.",
            });
        }
        if (!isAbsolute(path)) {
            return res.status(400).json({
                success: false,
                message: "The image path must be absolute; a relative path cannot be resolved on the analysis service.",
            });
        }

        const nameInput = typeof req.body?.name === "string" ? req.body.name.trim() : "";
        const name = nameInput || basename(path) || path;

        const duplicate = await prisma.diskImage.findFirst({ where: { userId, path } });
        if (duplicate) {
            return res.status(409).json({
                success: false,
                message: `You have already registered an image at ${path}.`,
            });
        }

        const call = await identifyDiskImage(path);
        if (!call.ok) {
            return vendorFailureResponse(res, call);
        }

        const detected = call.body.data as ServiceDiskIdentifyData | undefined;
        if (!detected || toVendorEnum(detected.vendor) === DeviceVendor.UNKNOWN) {
            // Not a failure of the service: the image is readable, it simply
            // carries no filesystem this platform's parsers understand yet.
            return res.status(422).json({
                success: false,
                message: call.message,
            });
        }

        const image = await prisma.diskImage.create({
            data: {
                userId,
                name,
                path,
                vendor: toVendorEnum(detected.vendor),
                family: toFamilyEnum(detected.family),
            },
        });

        await recordDiskImageEvent(
            image.id,
            userId,
            "DISK_IMAGE_REGISTERED",
            `Registered ${name} at ${path} (${detected.vendor}).`
        );

        return res.status(201).json({
            success: true,
            message: call.message,
            data: { image: toSerializable(image) },
        });
    } catch (error) {
        return res.status(500).json({
            success: false,
            message: "An error occurred while registering the disk image.",
            error: error instanceof Error ? error.message : String(error),
        });
    }
}

export async function listDiskImagesHandler(req: Request, res: Response<ApiResponse>) {
    try {
        const userId = req.userId;
        if (!userId) {
            return unauthorized(res);
        }

        const images = await prisma.diskImage.findMany({
            where: { userId },
            orderBy: { createdAt: "desc" },
            include: {
                _count: {
                    select: { recordings: true, recoveredBlocks: true, artifacts: true, events: true },
                },
            },
        });

        const payload = images.map(({ _count, ...image }) => ({
            ...image,
            counts: _count,
        }));

        return res.status(200).json({
            success: true,
            message: `Retrieved ${payload.length} disk image(s).`,
            data: toSerializable({ images: payload }),
        });
    } catch (error) {
        return res.status(500).json({
            success: false,
            message: "An error occurred while listing your disk images.",
            error: error instanceof Error ? error.message : String(error),
        });
    }
}

export async function getDiskImageHandler(req: Request, res: Response<ApiResponse>) {
    try {
        const userId = req.userId;
        if (!userId) {
            return unauthorized(res);
        }
        const diskImageId = diskImageIdFrom(req);

        const image = await loadDiskImageResource(userId, diskImageId);
        if (!image) {
            return notFound(res);
        }

        return res.status(200).json({
            success: true,
            message: "Disk image retrieved successfully.",
            // The image is returned as one complete resource rather than as
            // sibling collections, so a consumer models a single object.
            data: toSerializable({ image }),
        });
    } catch (error) {
        return res.status(500).json({
            success: false,
            message: "An error occurred while retrieving the disk image.",
            error: error instanceof Error ? error.message : String(error),
        });
    }
}

export async function deleteDiskImageHandler(req: Request, res: Response<ApiResponse>) {
    try {
        const userId = req.userId;
        if (!userId) {
            return unauthorized(res);
        }
        const diskImageId = diskImageIdFrom(req);

        const image = await findOwnedDiskImage(userId, diskImageId);
        if (!image) {
            return notFound(res);
        }

        await prisma.diskImage.delete({ where: { id: diskImageId } });

        return res.status(200).json({
            success: true,
            message: `Disk image ${image.name} and all of its evidence records were deleted.`,
            data: { id: diskImageId },
        });
    } catch (error) {
        return res.status(500).json({
            success: false,
            message: "An error occurred while deleting the disk image.",
            error: error instanceof Error ? error.message : String(error),
        });
    }
}

export async function analyseDiskImageHandler(req: Request, res: Response<ApiResponse>) {
    try {
        const userId = req.userId;
        if (!userId) {
            return unauthorized(res);
        }
        const diskImageId = diskImageIdFrom(req);

        const image = await findOwnedDiskImage(userId, diskImageId);
        if (!image) {
            return notFound(res);
        }

        if (req.body?.carve !== undefined && typeof req.body.carve !== "boolean") {
            return res.status(400).json({
                success: false,
                message: "The carve flag must be true or false.",
            });
        }
        const carve = req.body?.carve === undefined ? true : (req.body.carve as boolean);

        let carveLimit = 8;
        if (req.body?.carveLimit !== undefined) {
            const parsed = Number(req.body.carveLimit);
            if (!Number.isInteger(parsed) || parsed < 1 || parsed > 200) {
                return res.status(400).json({
                    success: false,
                    message: "The carveLimit field must be a whole number between 1 and 200.",
                });
            }
            carveLimit = parsed;
        }

        if (req.body?.computeHash !== undefined && typeof req.body.computeHash !== "boolean") {
            return res.status(400).json({
                success: false,
                message: "The computeHash flag must be true or false.",
            });
        }
        const computeHash = req.body?.computeHash === undefined ? true : (req.body.computeHash as boolean);

        if (req.body?.verifyDecode !== undefined && typeof req.body.verifyDecode !== "boolean") {
            return res.status(400).json({
                success: false,
                message: "The verifyDecode flag must be true or false.",
            });
        }
        const verifyDecode = req.body?.verifyDecode === undefined ? true : (req.body.verifyDecode as boolean);

        try {
            await transitionDiskImage(diskImageId, userId, DiskImageState.ANALYSING, "Disk analysis started.");
        } catch (error) {
            const conflict = transitionFailureResponse(res, error);
            if (conflict) {
                return conflict;
            }
            throw error;
        }

        const call = await analyseDiskImage({
            path: image.path,
            carve,
            carve_limit: carveLimit,
            compute_hash: computeHash,
            verify_decode: verifyDecode,
        });

        if (!call.ok) {
            await markDiskImageFailed(diskImageId, userId, call.code, `Analysis failed: ${call.message}`);
            return vendorFailureResponse(res, call);
        }

        const evidence = call.body.evidence as ServiceVolumeEvidence | undefined;
        if (!evidence) {
            await markDiskImageFailed(diskImageId, userId, "PROTOCOL_ERROR", "Analysis returned no evidence.");
            return res.status(502).json({
                success: false,
                message: "The analysis service reported success but returned no evidence object.",
            });
        }

        await persistVolumeEvidence(diskImageId, evidence);

        await transitionDiskImage(
            diskImageId,
            userId,
            DiskImageState.ANALYSED,
            `Parsed ${evidence.recordings.length} indexed recording(s), ${evidence.recovered_blocks.length} unreferenced block(s), and carved ${evidence.artifacts.length} artifact(s).`,
            "DISK_IMAGE_ANALYSED"
        );

        const resource = await loadDiskImageResource(userId, diskImageId);

        return res.status(200).json({
            success: true,
            message: call.message,
            data: toSerializable({
                // The complete resource, matching getDiskImageHandler: the
                // client renders this response directly, so a bare image row
                // would blank the recordings, blocks and artifacts it just
                // populated.
                image: resource,
                // Timeline gaps are derived from the recordings above rather
                // than stored, so they are surfaced here rather than as a
                // fifth table with nothing new to say once recordings exist.
                gaps: toCamelCaseDeep(evidence.gaps),
                warnings: evidence.warnings,
            }),
        });
    } catch (error) {
        const conflict = transitionFailureResponse(res, error);
        if (conflict) {
            return conflict;
        }
        return res.status(500).json({
            success: false,
            message: "An error occurred while analysing the disk image.",
            error: error instanceof Error ? error.message : String(error),
        });
    }
}
