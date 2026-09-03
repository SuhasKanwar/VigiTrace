import NodeCache from "node-cache";

class CacheService {
    private cache: NodeCache;

    public static generateCacheKey(prefix: string, params: Record<string, unknown>): string {
        return `${prefix}:${JSON.stringify(params)}`;
    }

    constructor(ttlSeconds = 300) {
        this.cache = new NodeCache({
            stdTTL: ttlSeconds,
            checkperiod: Math.max(1, Math.floor(ttlSeconds * 0.2)),
        });
    }

    public get<T>(key: string): T | undefined {
        return this.cache.get<T>(key);
    }

    public set<T>(key: string, value: T, ttl?: number): boolean {
        if (ttl !== undefined) {
            return this.cache.set(key, value, ttl);
        }
        return this.cache.set(key, value);
    }

    public has(key: string): boolean {
        return this.cache.has(key);
    }

    public del(keys: string | string[]): number {
        return this.cache.del(keys);
    }

    public flush(): void {
        this.cache.flushAll();
    }

    public getStats(): NodeCache.Stats {
        return this.cache.getStats();
    }
}

export const cacheService = new CacheService();

export default CacheService;