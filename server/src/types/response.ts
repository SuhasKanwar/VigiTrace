export type ApiResponse = {
    success: boolean;
    message: string;
    data?: unknown;
    error?: unknown;
};