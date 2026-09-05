import { Router } from "express";
import authenticate from "../middlewares/authenticate.js";
import {
    analyseDiskImageHandler,
    createDiskImageHandler,
    deleteDiskImageHandler,
    getDiskImageHandler,
    listDiskImagesHandler,
} from "../controllers/diskController.js";

const diskRouter = Router();

// Every disk image route is scoped to the authenticated investigator: an
// acquired volume and its recovered evidence are never shared across users.
diskRouter.use(authenticate);

diskRouter.post("/", createDiskImageHandler);
diskRouter.get("/", listDiskImagesHandler);
diskRouter.get("/:id", getDiskImageHandler);
diskRouter.delete("/:id", deleteDiskImageHandler);

diskRouter.post("/:id/analyse", analyseDiskImageHandler);

export default diskRouter;
