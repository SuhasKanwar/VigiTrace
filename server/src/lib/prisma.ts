import { PrismaPg } from "@prisma/adapter-pg";
import { PrismaClient } from "../generated/prisma/client.js";
import { DATABASE_URL } from "./config.js";

const adapter = new PrismaPg({
    connectionString: DATABASE_URL
});
const prisma = new PrismaClient({
    adapter
});

export default prisma;