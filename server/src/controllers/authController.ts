import type { Request, Response } from "express";
import bcrypt from "bcrypt";
import prisma from "../lib/prisma.js";
import { buildAuthResponse } from "../utils/auth.js";
import type { ApiResponse } from "../types/response.js";
import { NODE_ENV } from "../lib/config.js";
import { AuthProvider } from "../generated/prisma/enums.js";

export async function signUpHandler(req: Request, res: Response<ApiResponse>) {
    try {
        const name = typeof req.body?.name === "string" ? req.body.name.trim() : "";
        const email = typeof req.body?.email === "string" ? req.body.email.trim().toLowerCase() : "";
        const password = req.body?.password;
        const imageUrl = req.body?.imageUrl;
        if(!name || !email || typeof password !== "string" || !password) {
            return res.status(400).json({
                success: false,
                message: "Name, email, and password are required.",
            });
        }

        const existingUser = await prisma.user.findFirst({
            where: { email: { equals: email, mode: "insensitive" } },
        });

        if (existingUser) {
            return res.status(409).json({
                success: false,
                message: "User with this email already exists.",
            });
        }
        
        const hashedPassword = await bcrypt.hash(password, 10);
        const user = await prisma.user.create({
            data: {
                name,
                email,
                password: hashedPassword,
                provider: AuthProvider.CREDENTIALS,
                imageUrl: imageUrl || null,
            },
        });
        const authResponseData = buildAuthResponse(user);
        res.cookie("Authorization", authResponseData.token, {
            secure: NODE_ENV === "production",
            sameSite: "lax",
            httpOnly: NODE_ENV === "production",
        });
        return res.status(201).json({
            success: true,
            message: "User registered successfully.",
            data: authResponseData,
        });
    } catch (error) {
        console.error("Error during sign-up:", error);
        return res.status(500).json({
            success: false,
            message: "An error occurred during sign-up.",
            error: error instanceof Error ? error.message : String(error),
        });
    }
}

export async function signInHandler(req: Request, res: Response<ApiResponse>) {
    try {
        const email = typeof req.body?.email === "string" ? req.body.email.trim().toLowerCase() : "";
        const password = req.body?.password;
        if(!email) {
            return res.status(400).json({
                success: false,
                message: "Email is required.",
            });
        }

        const user = await prisma.user.findFirst({
            where: { email: { equals: email, mode: "insensitive" } },
        });

        if (!user) {
            return res.status(401).json({
                success: false,
                message: "Invalid email.",
            });
        }

        if (user.provider === AuthProvider.GOOGLE) {
            return res.status(401).json({
                success: false,
                message: "This account uses Google sign-in. Continue with Google instead of a password.",
            });
        }

        if (typeof password !== "string" || !password) {
            return res.status(400).json({
                success: false,
                message: "Password is required for credential-based accounts.",
            });
        }

        if (!user.password) {
            return res.status(500).json({
                success: false,
                message: "This account is missing a password hash.",
            });
        }

        const isPasswordValid = await bcrypt.compare(password, user.password);
        if (!isPasswordValid) {
            return res.status(401).json({
                success: false,
                message: "Invalid password.",
            });
        }
        return res.status(200).json({
            success: true,
            message: "User signed in successfully.",
            data: buildAuthResponse(user),
        });
    } catch (error) {
        return res.status(500).json({
            success: false,
            message: "An error occurred during sign-in.",
            error: error instanceof Error ? error.message : String(error),
        });
    }
}

export async function signOutHandler(req: Request, res: Response<ApiResponse>) {
    try {
        res.clearCookie("Authorization", {
            secure: NODE_ENV === "production",
            sameSite: "lax",
        });
        return res.status(200).json({
            success: true,
            message: "User signed out successfully.",
        });
    } catch (error) {
        return res.status(500).json({
            success: false,
            message: "An error occurred during sign-out.",
            error: error instanceof Error ? error.message : String(error),
        });
    }
}

export async function googleAuthHandler(req: Request, res: Response<ApiResponse>) {
    try {
        const name = req.body?.name;
        const email = typeof req.body?.email === "string" ? req.body.email.trim().toLowerCase() : "";
        const imageUrl = req.body?.imageUrl;

        if (!email) {
            return res.status(400).json({
                success: false,
                message: "Email is required.",
            });
        }

        const existingUser = await prisma.user.findFirst({
            where: { email: { equals: email, mode: "insensitive" } },
        });

        if (existingUser) {
            const updatedUser = await prisma.user.update({
                where: { id: existingUser.id },
                data: {
                    name: name ?? existingUser.name,
                    provider: AuthProvider.GOOGLE,
                    imageUrl: imageUrl ?? existingUser.imageUrl,
                    password: existingUser.password ?? null,
                },
            });

            return res.status(200).json({
                success: true,
                message: "Google account confirmed successfully.",
                data: buildAuthResponse(updatedUser),
            });
        }

        const user = await prisma.user.create({
            data: {
                name: name ?? null,
                email,
                provider: AuthProvider.GOOGLE,
                imageUrl: imageUrl ?? null,
                password: null,
            },
        });

        return res.status(201).json({
            success: true,
            message: "Google account created successfully.",
            data: buildAuthResponse(user),
        });
    } catch (error) {
        return res.status(500).json({
            success: false,
            message: "An error occurred while confirming Google sign-in.",
            error: error instanceof Error ? error.message : String(error),
        });
    }
}
