import axios from "axios";
import { HTTP_SERVER_BASE_URL } from "./config";
import { pushToast } from "./toast";

declare module "axios" {
    interface AxiosRequestConfig {
        silentToast?: boolean;
        skipAuth?: boolean;
    }
}

const api = axios.create({
    baseURL: HTTP_SERVER_BASE_URL,
    withCredentials: true,
});

// `getSession()` is browser-only: it reads the NextAuth session endpoint through
// the document's cookies. This instance is also used server-side inside the
// NextAuth callbacks (src/app/api/auth/[...nextauth]/options.ts), where there is
// no document, no session cookie, and no token yet - the request being made is
// the one that mints it. Calling getSession() there would fetch a relative URL
// with no cookies and either throw or hang, so on the server the request is left
// untouched and goes out unauthenticated, exactly as it did before.
const isBrowser = typeof window !== "undefined";

let pendingSession: Promise<string | null> | null = null;

function readAccessToken(): Promise<string | null> {
    if (!pendingSession) {
        // Imported lazily so `next-auth/react` is never pulled into a server bundle.
        pendingSession = import("next-auth/react")
            .then(({ getSession }) => getSession())
            .then((session) => session?.accessToken ?? null)
            .catch(() => null);
        // Concurrent requests share one session lookup; the next request re-reads it.
        pendingSession.finally(() => {
            pendingSession = null;
        });
    }

    return pendingSession;
}

let interceptorsInstalled = false;

if (!interceptorsInstalled) {
    interceptorsInstalled = true;

    api.interceptors.request.use(async (config) => {
        if (!isBrowser || config.skipAuth || config.headers.has("Authorization")) {
            return config;
        }

        const accessToken = await readAccessToken();

        if (accessToken) {
            config.headers.set("Authorization", `Bearer ${accessToken}`);
        }

        return config;
    });

    api.interceptors.response.use(
        (response) => {
            const message = response.data?.message;

            if (!response.config.silentToast && response.config.method !== "get" && typeof message === "string" && message.trim()) {
                pushToast({ message, variant: "success" });
            }

            return response;
        },
        (error) => {
            const message =
                error?.response?.data?.message ??
                error?.message ??
                "Request failed.";

            if (!error?.config?.silentToast && typeof message === "string" && message.trim()) {
                pushToast({ message, variant: "error" });
            }

            return Promise.reject(error);
        }
    );
}

export default api;
