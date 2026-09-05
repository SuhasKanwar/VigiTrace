-- CreateEnum
CREATE TYPE "DiskImageState" AS ENUM ('REGISTERED', 'ANALYSING', 'ANALYSED', 'UNSUPPORTED', 'FAILED');

-- CreateTable
CREATE TABLE "DiskImage" (
    "id" TEXT NOT NULL,
    "userId" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "path" TEXT NOT NULL,
    "sizeBytes" BIGINT,
    "sha256" TEXT,
    "vendor" "DeviceVendor" NOT NULL DEFAULT 'UNKNOWN',
    "family" "DeviceFamily" NOT NULL DEFAULT 'UNKNOWN',
    "formatVersion" TEXT,
    "state" "DiskImageState" NOT NULL DEFAULT 'REGISTERED',
    "examinedAt" TIMESTAMP(3),
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "DiskImage_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "DiskRecording" (
    "id" TEXT NOT NULL,
    "diskImageId" TEXT NOT NULL,
    "channel" INTEGER NOT NULL,
    "startTime" TIMESTAMP(3),
    "endTime" TIMESTAMP(3),
    "durationSeconds" DOUBLE PRECISION,
    "dataOffset" BIGINT NOT NULL,
    "unfinalised" BOOLEAN NOT NULL DEFAULT false,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "DiskRecording_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "RecoveredBlock" (
    "id" TEXT NOT NULL,
    "diskImageId" TEXT NOT NULL,
    "blockIndex" INTEGER NOT NULL,
    "dataOffset" BIGINT NOT NULL,
    "packHeaders" INTEGER NOT NULL,
    "keyframeBoundaries" INTEGER NOT NULL,
    "channel" INTEGER,
    "timestamp" TIMESTAMP(3),
    "confidence" TEXT NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "RecoveredBlock_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "CarvedArtifact" (
    "id" TEXT NOT NULL,
    "diskImageId" TEXT NOT NULL,
    "channel" INTEGER NOT NULL,
    "dataOffset" BIGINT NOT NULL,
    "storedPath" TEXT NOT NULL,
    "sizeBytes" BIGINT NOT NULL,
    "sha256" TEXT NOT NULL,
    "keyframeAligned" BOOLEAN NOT NULL,
    "source" TEXT NOT NULL,
    "decoded" BOOLEAN NOT NULL DEFAULT false,
    "codec" TEXT,
    "width" INTEGER,
    "height" INTEGER,
    "frames" INTEGER,
    "decodeReason" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "CarvedArtifact_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "DiskImageEvent" (
    "id" TEXT NOT NULL,
    "diskImageId" TEXT NOT NULL,
    "userId" TEXT NOT NULL,
    "action" TEXT NOT NULL,
    "fromState" "DiskImageState",
    "toState" "DiskImageState",
    "detail" TEXT,
    "digest" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "DiskImageEvent_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE INDEX "DiskImage_userId_idx" ON "DiskImage"("userId");

-- CreateIndex
CREATE INDEX "DiskImage_state_idx" ON "DiskImage"("state");

-- CreateIndex
CREATE UNIQUE INDEX "DiskImage_userId_path_key" ON "DiskImage"("userId", "path");

-- CreateIndex
CREATE INDEX "DiskRecording_diskImageId_idx" ON "DiskRecording"("diskImageId");

-- CreateIndex
CREATE UNIQUE INDEX "DiskRecording_diskImageId_dataOffset_key" ON "DiskRecording"("diskImageId", "dataOffset");

-- CreateIndex
CREATE INDEX "RecoveredBlock_diskImageId_idx" ON "RecoveredBlock"("diskImageId");

-- CreateIndex
CREATE UNIQUE INDEX "RecoveredBlock_diskImageId_blockIndex_key" ON "RecoveredBlock"("diskImageId", "blockIndex");

-- CreateIndex
CREATE INDEX "CarvedArtifact_diskImageId_idx" ON "CarvedArtifact"("diskImageId");

-- CreateIndex
CREATE UNIQUE INDEX "CarvedArtifact_diskImageId_storedPath_key" ON "CarvedArtifact"("diskImageId", "storedPath");

-- CreateIndex
CREATE INDEX "DiskImageEvent_diskImageId_createdAt_idx" ON "DiskImageEvent"("diskImageId", "createdAt");

-- AddForeignKey
ALTER TABLE "DiskImage" ADD CONSTRAINT "DiskImage_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "DiskRecording" ADD CONSTRAINT "DiskRecording_diskImageId_fkey" FOREIGN KEY ("diskImageId") REFERENCES "DiskImage"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "RecoveredBlock" ADD CONSTRAINT "RecoveredBlock_diskImageId_fkey" FOREIGN KEY ("diskImageId") REFERENCES "DiskImage"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "CarvedArtifact" ADD CONSTRAINT "CarvedArtifact_diskImageId_fkey" FOREIGN KEY ("diskImageId") REFERENCES "DiskImage"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "DiskImageEvent" ADD CONSTRAINT "DiskImageEvent_diskImageId_fkey" FOREIGN KEY ("diskImageId") REFERENCES "DiskImage"("id") ON DELETE CASCADE ON UPDATE CASCADE;
