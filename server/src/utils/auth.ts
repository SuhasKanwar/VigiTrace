import jwt from "jsonwebtoken";
import { JWT_SECRET } from "../lib/config.js";
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
    const token = jwt.sign({ userId: user.id }, JWT_SECRET);

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