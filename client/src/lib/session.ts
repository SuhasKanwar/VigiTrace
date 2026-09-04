import { getServerSession } from "next-auth";
import { authOptions } from "@/app/api/auth/[...nextauth]/options";

export function getAuthSession() {
    return getServerSession(authOptions);
}