import jwt from "jsonwebtoken";
import type { Response } from "express";
import { JWT_EXPIRES_IN, JWT_SECRET, NODE_ENV } from "../lib/config.js";
import { AuthProvider } from "../generated/prisma/enums.js";

export function buildAuthResponse(user: {
    id: string;
    name: string | null;
    email: string;
    imageUrl: string | null;
    provider: AuthProvider;
    createdAt: Date;
    updatedAt: Date;
}) {
    // Tokens must expire: an unbounded credential cannot be revoked by waiting.
    const options = { expiresIn: JWT_EXPIRES_IN } as jwt.SignOptions;
    const token = jwt.sign({ userId: user.id }, JWT_SECRET, options);

    return {
        user: {
            id: user.id,
            name: user.name,
            email: user.email,
            imageUrl: user.imageUrl,
            provider: user.provider,
            createdAt: user.createdAt,
            updatedAt: user.updatedAt,
        },
        token,
    };
}

/** Every successful authentication sets the same cookie, whatever the provider. */
export function setAuthCookie(res: Response, token: string) {
    res.cookie("Authorization", token, {
        secure: NODE_ENV === "production",
        sameSite: "lax",
        httpOnly: NODE_ENV === "production",
    });
}
