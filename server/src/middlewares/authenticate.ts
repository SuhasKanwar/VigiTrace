import type { NextFunction, Request, Response } from "express";
import jwt from "jsonwebtoken";
import { JWT_SECRET } from "../lib/config.js";
import type { ApiResponse } from "../types/response.js";

export default function authenticate(req: Request, res: Response<ApiResponse>, next: NextFunction) {
    try {
        const authorization = req.get("Authorization");
        const token = authorization?.startsWith("Bearer ")
            ? authorization.slice("Bearer ".length)
            : req.cookies["Authorization"];
        if (!token) {
            return res.status(401).json({
                success: false,
                message: "Authentication token is missing.",
            });
        }

        const decoded = jwt.verify(token, JWT_SECRET) as { userId: string };
        req.userId = decoded.userId;
        next();
    } catch (error) {
        return res.status(401).json({
            success: false,
            message: "Unauthorized access.",
            error: error instanceof Error ? error.message : String(error),
        });
    }
}