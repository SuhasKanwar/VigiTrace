-- CreateEnum
CREATE TYPE "DeviceState" AS ENUM ('REGISTERED', 'IDENTIFYING', 'IDENTIFIED', 'ENUMERATING', 'ENUMERATED', 'INDEXING', 'INDEXED', 'ACQUIRING', 'ACQUIRED', 'VERIFYING', 'VERIFIED', 'UNREACHABLE', 'AUTH_FAILED', 'UNSUPPORTED', 'FAILED');

-- CreateEnum
CREATE TYPE "DeviceVendor" AS ENUM ('HIKVISION', 'DAHUA', 'CPPLUS', 'GODREJ', 'UNKNOWN');

-- CreateEnum
CREATE TYPE "DeviceFamily" AS ENUM ('HIKVISION', 'DAHUA', 'XIONGMAI', 'UNKNOWN');

-- CreateEnum
CREATE TYPE "IdentificationConfidence" AS ENUM ('CONFIRMED', 'PROBABLE', 'UNKNOWN');

-- CreateEnum
CREATE TYPE "DeviceKind" AS ENUM ('DVR', 'NVR', 'XVR', 'HVR', 'IPC', 'UNKNOWN');

-- CreateTable
CREATE TABLE "Device" (
    "id" TEXT NOT NULL,
    "userId" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "host" TEXT NOT NULL,
    "httpPort" INTEGER NOT NULL DEFAULT 80,
    "useHttps" BOOLEAN NOT NULL DEFAULT false,
    "username" TEXT,
    "password" TEXT,
    "vendorHint" "DeviceVendor",
    "vendor" "DeviceVendor" NOT NULL DEFAULT 'UNKNOWN',
    "family" "DeviceFamily" NOT NULL DEFAULT 'UNKNOWN',
    "state" "DeviceState" NOT NULL DEFAULT 'REGISTERED',
    "confidence" "IdentificationConfidence" NOT NULL DEFAULT 'UNKNOWN',
    "kind" "DeviceKind" NOT NULL DEFAULT 'UNKNOWN',
    "modelName" TEXT,
    "serialNumber" TEXT,
    "firmwareVersion" TEXT,
    "hardwareVersion" TEXT,
    "macAddress" TEXT,
    "driftSeconds" DOUBLE PRECISION,
    "timezone" TEXT,
    "lastProbedAt" TIMESTAMP(3),
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "Device_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "DeviceProbe" (
    "id" TEXT NOT NULL,
    "deviceId" TEXT NOT NULL,
    "method" TEXT NOT NULL,
    "success" BOOLEAN NOT NULL,
    "startedAt" TIMESTAMP(3) NOT NULL,
    "finishedAt" TIMESTAMP(3) NOT NULL,
    "durationMs" INTEGER NOT NULL,
    "evidenceDigest" TEXT,
    "endpointsAttempted" TEXT[],
    "endpointsSucceeded" TEXT[],
    "warnings" TEXT[],
    "errorCode" TEXT,
    "errorMessage" TEXT,
    "raw" JSONB,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "DeviceProbe_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "DeviceChannel" (
    "id" TEXT NOT NULL,
    "deviceId" TEXT NOT NULL,
    "channelId" TEXT NOT NULL,
    "name" TEXT,
    "enabled" BOOLEAN,
    "isAnalog" BOOLEAN,
    "codec" TEXT,
    "resolution" TEXT,
    "trackId" TEXT,

    CONSTRAINT "DeviceChannel_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "DeviceStorage" (
    "id" TEXT NOT NULL,
    "deviceId" TEXT NOT NULL,
    "storageId" TEXT NOT NULL,
    "name" TEXT,
    "kind" TEXT,
    "status" TEXT,
    "capacityBytes" BIGINT,
    "freeBytes" BIGINT,
    "storageProperty" TEXT,

    CONSTRAINT "DeviceStorage_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "Recording" (
    "id" TEXT NOT NULL,
    "deviceId" TEXT NOT NULL,
    "recordingId" TEXT NOT NULL,
    "channelId" TEXT NOT NULL,
    "startTime" TIMESTAMP(3) NOT NULL,
    "endTime" TIMESTAMP(3) NOT NULL,
    "codec" TEXT,
    "sizeBytes" BIGINT,
    "playbackUri" TEXT,
    "filePath" TEXT,
    "eventType" TEXT,
    "recordTrigger" TEXT,
    "overwriteCount" INTEGER,
    "raw" JSONB,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "Recording_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "Acquisition" (
    "id" TEXT NOT NULL,
    "deviceId" TEXT NOT NULL,
    "recordingId" TEXT NOT NULL,
    "channelId" TEXT NOT NULL,
    "storedPath" TEXT NOT NULL,
    "sizeBytes" BIGINT NOT NULL,
    "md5" TEXT NOT NULL,
    "sha256" TEXT NOT NULL,
    "container" TEXT,
    "acquiredAt" TIMESTAMP(3) NOT NULL,
    "durationMs" INTEGER NOT NULL,
    "sourceUri" TEXT,
    "verified" BOOLEAN NOT NULL DEFAULT false,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "Acquisition_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "CustodyEvent" (
    "id" TEXT NOT NULL,
    "deviceId" TEXT NOT NULL,
    "userId" TEXT NOT NULL,
    "action" TEXT NOT NULL,
    "fromState" "DeviceState",
    "toState" "DeviceState",
    "detail" TEXT,
    "digest" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "CustodyEvent_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE INDEX "Device_userId_idx" ON "Device"("userId");

-- CreateIndex
CREATE INDEX "Device_state_idx" ON "Device"("state");

-- CreateIndex
CREATE UNIQUE INDEX "Device_userId_host_httpPort_key" ON "Device"("userId", "host", "httpPort");

-- CreateIndex
CREATE INDEX "DeviceProbe_deviceId_createdAt_idx" ON "DeviceProbe"("deviceId", "createdAt");

-- CreateIndex
CREATE INDEX "DeviceChannel_deviceId_idx" ON "DeviceChannel"("deviceId");

-- CreateIndex
CREATE UNIQUE INDEX "DeviceChannel_deviceId_channelId_key" ON "DeviceChannel"("deviceId", "channelId");

-- CreateIndex
CREATE INDEX "DeviceStorage_deviceId_idx" ON "DeviceStorage"("deviceId");

-- CreateIndex
CREATE UNIQUE INDEX "DeviceStorage_deviceId_storageId_key" ON "DeviceStorage"("deviceId", "storageId");

-- CreateIndex
CREATE INDEX "Recording_deviceId_channelId_startTime_idx" ON "Recording"("deviceId", "channelId", "startTime");

-- CreateIndex
CREATE UNIQUE INDEX "Recording_deviceId_recordingId_key" ON "Recording"("deviceId", "recordingId");

-- CreateIndex
CREATE INDEX "Acquisition_deviceId_createdAt_idx" ON "Acquisition"("deviceId", "createdAt");

-- CreateIndex
CREATE INDEX "CustodyEvent_deviceId_createdAt_idx" ON "CustodyEvent"("deviceId", "createdAt");

-- AddForeignKey
ALTER TABLE "Device" ADD CONSTRAINT "Device_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "DeviceProbe" ADD CONSTRAINT "DeviceProbe_deviceId_fkey" FOREIGN KEY ("deviceId") REFERENCES "Device"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "DeviceChannel" ADD CONSTRAINT "DeviceChannel_deviceId_fkey" FOREIGN KEY ("deviceId") REFERENCES "Device"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "DeviceStorage" ADD CONSTRAINT "DeviceStorage_deviceId_fkey" FOREIGN KEY ("deviceId") REFERENCES "Device"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Recording" ADD CONSTRAINT "Recording_deviceId_fkey" FOREIGN KEY ("deviceId") REFERENCES "Device"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Acquisition" ADD CONSTRAINT "Acquisition_deviceId_fkey" FOREIGN KEY ("deviceId") REFERENCES "Device"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "CustodyEvent" ADD CONSTRAINT "CustodyEvent_deviceId_fkey" FOREIGN KEY ("deviceId") REFERENCES "Device"("id") ON DELETE CASCADE ON UPDATE CASCADE;
