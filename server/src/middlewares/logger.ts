import type { NextFunction, Request, Response } from "express";
import fs from "fs";
import { LOGS_DIRECTORY } from "../lib/config.js";

export default function logger(req: Request, res: Response, next: NextFunction) {
    if (!fs.existsSync(LOGS_DIRECTORY)) {
        fs.mkdirSync(LOGS_DIRECTORY);
    }
    const logStream = fs.createWriteStream(`${LOGS_DIRECTORY}/log-${new Date().toISOString().split("T")[0]}.log`, { flags: "a" });
    logStream.write(`[${new Date().toISOString()}] ${req.method} ${req.url} ${res.statusCode}\n`);
    logStream.end();
    next();
}