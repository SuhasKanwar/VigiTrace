import express, { type Request, type Response } from 'express';
import type { ApiResponse } from './types/response.js';
import { ALLOWED_ORIGINS, PORT } from './lib/config.js';
import cors from 'cors';
import logger from './middlewares/logger.js';
import authRouter from './routes/authRouter.js';
import cookieParser from 'cookie-parser';
import dotenv from 'dotenv';
import authenticate from "./middlewares/authenticate.js";

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
app.listen(PORT, (err) => {
    if (err) {
        console.error("Error starting server ->", err);
    } else {
        console.log(`Server is running on port -> ${PORT}`);
    }
});