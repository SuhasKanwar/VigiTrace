import type { NextAuthOptions } from "next-auth";
import CredentialsProvider from "next-auth/providers/credentials";
import GoogleProvider from "next-auth/providers/google";
import api from "@/lib/api";
import { GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, NEXTAUTH_SECRET } from "@/lib/config";

type GoogleProfile = {
    sub?: string;
    name?: string;
    email?: string;
    picture?: string;
};

export const authOptions: NextAuthOptions = {
    providers: [
        GoogleProvider({
            clientId: GOOGLE_CLIENT_ID,
            clientSecret: GOOGLE_CLIENT_SECRET,
            profile(profile) {
                if (!profile || !profile.sub) {
                    throw new Error("Google profile 'sub' (id) missing");
                }
                return {
                    id: profile.sub,
                    name: profile.name,
                    email: profile.email,
                    image: profile.picture,
                };
            },
            allowDangerousEmailAccountLinking: true
        }),
        CredentialsProvider({
            name: "Credentials",
            credentials: {
                name: { label: "Name", type: "text" },
                email: { label: "Email", type: "email" },
                password: { label: "Password", type: "password" },
                register: { label: "Register", type: "text" },
            },
            async authorize(credentials) {
                const name = credentials?.name?.trim();
                const email = credentials?.email?.trim();
                const password = credentials?.password;
                const isRegistering = credentials?.register === "true";

                if (!email || !password) {
                    throw new Error("Email and password are required.");
                }

                if (isRegistering && !name) {
                    throw new Error("Name is required to create an account.");
                }

                try {
                    const response = isRegistering
                        ? await api.post("/api/auth/signup", {
                              name,
                              email,
                              password,
                          })
                        : await api.post("/api/auth/signin", {
                              email,
                              password,
                          });

                    const authData = response.data?.data;

                    if (!authData?.user || !authData?.token) {
                        throw new Error("Invalid authentication response from the server.");
                    }

                    return {
                        id: authData.user.id,
                        name: authData.user.name,
                        email: authData.user.email,
                        image: authData.user.imageUrl ?? undefined,
                        accessToken: authData.token,
                    };
                } catch (error) {
                    const message =
                        error instanceof Error
                            ? error.message
                            : isRegistering
                                ? "Unable to create your account. Please try again."
                                : "Unable to sign in. Please check your credentials and try again.";

                    throw new Error(message);
                }
            },
        })
    ],
    callbacks: {
        async signIn({ user }) {
            if (!user?.email) return false;
            return true;
        },
        async jwt({ token, user, account, profile }) {
            if (user) {
                token.id = user.id?.toString();
                token.accessToken = "accessToken" in user ? user.accessToken : token.accessToken;
            }

            if (account?.provider === "google" && profile) {
                const googleProfile = profile as GoogleProfile;

                if (!googleProfile.email) {
                    throw new Error("Google profile email is missing.");
                }

                const response = await api.post("/api/auth/google", {
                    name: googleProfile.name,
                    email: googleProfile.email,
                    imageUrl: googleProfile.picture ?? null,
                    providerId: googleProfile.sub,
                });

                const authData = response.data?.data;

                if (!authData?.user || !authData?.token) {
                    throw new Error("Invalid Google authentication response from the server.");
                }

                token.id = authData.user.id;
                token.accessToken = authData.token;
                token.provider = "google";
            }

            if (account?.provider === "credentials") {
                token.provider = "credentials";
            }

            return token;
        },
        async session({ session, token }) {
            if (token) {
                session.user.id = token.id;
                session.accessToken = token.accessToken;
            }
            return session;
        }
    },
    pages: {
        signIn: "/auth/signin",
        newUser: "/auth/signup",
        error: "/auth/error",
    },
    session: {
        strategy: "jwt"
    },
    secret: NEXTAUTH_SECRET
};
