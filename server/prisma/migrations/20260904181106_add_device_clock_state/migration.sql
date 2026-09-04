-- AlterTable
ALTER TABLE "Device" ADD COLUMN     "clockDeviceTime" TIMESTAMP(3),
ADD COLUMN     "clockDeviceTimeRaw" TEXT,
ADD COLUMN     "clockProbedAt" TIMESTAMP(3),
ADD COLUMN     "ntpEnabled" BOOLEAN,
ADD COLUMN     "ntpServers" TEXT[];
