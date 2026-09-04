import express, { type NextFunction, type Request, type Response } from 'express';
import type { ApiResponse } from './types/response.js';
import { ALLOWED_ORIGINS, NODE_ENV, PORT } from './lib/config.js';
import cors from 'cors';
import logger from './middlewares/logger.js';
import authRouter from './routes/authRouter.js';
import deviceRouter from './routes/deviceRouter.js';
import cookieParser from 'cookie-parser';
import dotenv from 'dotenv';

dotenv.config();

const app = express();

app.use(cors({
    origin: ALLOWED_ORIGINS,
    credentials: true
}));
app.use(express.json());
app.use(cookieParser());
app.use(express.urlencoded({ extended: true }));
app.use(logger);

app.get("/", (_req: Request, res: Response<ApiResponse>) => {
    res.json({
        success: true,
        message: "VigiTrace server is running successfully."
    });
});

app.get("/health", (_req: Request, res: Response<ApiResponse>) => {
    res.json({
        success: true,
        message: "VigiTrace server is healthy."
    });
});

app.use("/api/auth", authRouter);
app.use("/api/devices", deviceRouter);

app.use((req: Request, res: Response<ApiResponse>) => {
    res.status(404).json({
        success: false,
        message: `No route matches ${req.method} ${req.originalUrl} on this server.`,
    });
});

// Express 5 forwards rejected promises here, so a handler that throws still
// answers in the ApiResponse shape the client expects instead of an HTML page.
app.use((error: unknown, _req: Request, res: Response<ApiResponse>, next: NextFunction) => {
    if (res.headersSent) {
        return next(error);
    }
    console.error("Unhandled server error ->", error);
    const isBadJson =
        error instanceof SyntaxError && "body" in error && (error as { status?: number }).status === 400;
    return res.status(isBadJson ? 400 : 500).json({
        success: false,
        message: isBadJson
            ? "The request body could not be read as JSON."
            : "The server encountered an unexpected error.",
        error: NODE_ENV === "production"
            ? undefined
            : error instanceof Error ? error.message : String(error),
    });
});

app.listen(PORT, (err) => {
    if (err) {
        console.error("Error starting server ->", err);
    } else {
        console.log(`Server is running on port -> ${PORT}`);
    }
});
