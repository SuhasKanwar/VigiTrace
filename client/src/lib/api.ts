import axios from "axios";
import { HTTP_SERVER_BASE_URL } from "./config";
import { pushToast } from "./toast";

declare module "axios" {
    interface AxiosRequestConfig {
        silentToast?: boolean;
    }
}

const api = axios.create({
    baseURL: HTTP_SERVER_BASE_URL,
    withCredentials: true,
});

let interceptorsInstalled = false;

if (!interceptorsInstalled) {
    interceptorsInstalled = true;

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
