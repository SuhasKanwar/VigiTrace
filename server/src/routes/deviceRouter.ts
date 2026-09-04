import { Router } from "express";
import authenticate from "../middlewares/authenticate.js";
import {
    analyzeDeviceHandler,
    createAcquisitionHandler,
    createDeviceHandler,
    deleteDeviceHandler,
    detectDeviceHandler,
    enumerateDeviceHandler,
    getCustodyHandler,
    getDeviceHandler,
    getVendorsHandler,
    identifyDeviceHandler,
    listAcquisitionsHandler,
    listDevicesHandler,
    listRecordingsHandler,
    searchRecordingsHandler,
    updateDeviceHandler,
    verifyDeviceHandler,
} from "../controllers/deviceController.js";

const deviceRouter = Router();

// Every device route is scoped to the authenticated investigator: recorders,
// their evidence and their chain of custody are never shared across users.
deviceRouter.use(authenticate);

deviceRouter.get("/vendors", getVendorsHandler);

deviceRouter.post("/", createDeviceHandler);
deviceRouter.get("/", listDevicesHandler);
deviceRouter.get("/:id", getDeviceHandler);
deviceRouter.patch("/:id", updateDeviceHandler);
deviceRouter.delete("/:id", deleteDeviceHandler);

deviceRouter.post("/:id/detect", detectDeviceHandler);
deviceRouter.post("/:id/identify", identifyDeviceHandler);
deviceRouter.post("/:id/enumerate", enumerateDeviceHandler);

deviceRouter.post("/:id/recordings/search", searchRecordingsHandler);
deviceRouter.get("/:id/recordings", listRecordingsHandler);

deviceRouter.post("/:id/acquisitions", createAcquisitionHandler);
deviceRouter.get("/:id/acquisitions", listAcquisitionsHandler);

deviceRouter.post("/:id/verify", verifyDeviceHandler);

deviceRouter.get("/:id/custody", getCustodyHandler);
deviceRouter.post("/:id/analysis", analyzeDeviceHandler);

export default deviceRouter;
