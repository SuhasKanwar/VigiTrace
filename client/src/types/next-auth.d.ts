import 'next-auth';
import { DefaultSession } from 'next-auth';

declare module 'next-auth' {
    interface User {
        id?: string;
        name?: string;
        email: string;
        image?: string;
        accessToken?: string;
    }
    interface Session {
        user: {
            id?: string;
            name?: string;
            email: string;
            image?: string;
        } & DefaultSession['user'];
        accessToken?: string;
    }
}

declare module 'next-auth/jwt' {
    interface JWT {
        id?: string;
        accessToken?: string;
        provider?: string;
    }
}