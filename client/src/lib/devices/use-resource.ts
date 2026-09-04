"use client";

import { useCallback, useEffect, useState } from "react";
import { readErrorMessage } from "./api";

type ResourceState<T> = {
    data: T | null;
    error: string | null;
    loading: boolean;
    reload: () => Promise<void>;
    setData: (value: T) => void;
};

type Snapshot<T> = { data: T | null; error: string | null; loading: boolean };

/**
 * Loads one resource and keeps loading, empty, and error distinguishable. Failures
 * are already surfaced by the axios response interceptor's toast; the message is
 * held here only for the inline state and is never re-reported.
 */
export default function useResource<T>(load: () => Promise<T>): ResourceState<T> {
    const [state, setState] = useState<Snapshot<T>>({ data: null, error: null, loading: true });

    const settle = useCallback((data: T | null, error: string | null) => {
        setState({ data, error, loading: false });
    }, []);

    useEffect(() => {
        let active = true;

        load().then(
            (result) => {
                if (active) settle(result, null);
            },
            (cause: unknown) => {
                if (active) settle(null, readErrorMessage(cause));
            },
        );

        return () => {
            active = false;
        };
    }, [load, settle]);

    const reload = useCallback(async () => {
        setState((current) => ({ ...current, error: null, loading: true }));

        try {
            settle(await load(), null);
        } catch (cause) {
            settle(null, readErrorMessage(cause));
        }
    }, [load, settle]);

    const setData = useCallback((value: T) => {
        settle(value, null);
    }, [settle]);

    return { data: state.data, error: state.error, loading: state.loading, reload, setData };
}
