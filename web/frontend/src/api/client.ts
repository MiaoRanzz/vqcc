import { useCallback, useEffect, useState } from "react";
export interface Snapshot<T> {
  data: T;
  observed_at: string;
  source_updated_at: string | null;
  revision: number;
  freshness: string;
  consistency: string;
}
export interface Page<T> {
  items: T[];
  next_cursor: string | null;
  total?: number;
}
export type RecordData = Record<string, any>;
let csrf = "";
export const setCsrf = (value: string) => {
  csrf = value;
};
export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: RecordData,
  ) {
    super(
      [
        detail.message || detail.detail || `请求失败（${status}）`,
        ...Object.entries(detail.field_errors || {}).map(
          ([key, value]) => `${key}: ${value}`,
        ),
      ].join(" · "),
    );
  }
}
export async function request<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const response = await fetch(`/api/v1${path}`, {
    ...options,
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", ...options.headers },
  });
  const result = response.status === 204 ? null : await response.json();
  if (!response.ok) {
    if (response.status === 401)
      window.dispatchEvent(new Event("session-expired"));
    throw new ApiError(response.status, result);
  }
  return result;
}
const pending = new Map<string, string>(
  JSON.parse(sessionStorage.getItem("vqcc.pending-operations") || "[]"),
);
const savePending = () =>
  sessionStorage.setItem(
    "vqcc.pending-operations",
    JSON.stringify([...pending]),
  );
export async function mutate<T = RecordData>(
  path: string,
  body: unknown = {},
  method = "POST",
): Promise<T> {
  const json = JSON.stringify(body),
    fingerprint = `${method}:${path}:${json}`;
  const key = pending.get(fingerprint) || crypto.randomUUID();
  pending.set(fingerprint, key);
  savePending();
  try {
    const result = await request<T>(path, {
      method,
      headers: { "X-CSRF-Token": csrf, "Idempotency-Key": key },
      body: json,
    });
    pending.delete(fingerprint);
    savePending();
    window.dispatchEvent(new Event("console-update"));
    return result;
  } catch (error) {
    if (error instanceof ApiError && error.status < 500) {
      pending.delete(fingerprint);
      savePending();
    }
    throw error;
  }
}
export function useSnapshot<T = RecordData>(path: string | null, poll = true) {
  const [snapshot, setSnapshot] = useState<Snapshot<T> | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const refresh = useCallback(async () => {
    if (!path) {
      setLoading(false);
      return;
    }
    try {
      setSnapshot(await request<Snapshot<T>>(path));
      setError("");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [path]);
  useEffect(() => {
    setSnapshot(null);
    setLoading(true);
    void refresh();
  }, [refresh]);
  useEffect(() => {
    if (!poll) return;
    const timer = window.setInterval(refresh, 5000);
    const listener = () => void refresh();
    window.addEventListener("console-update", listener);
    return () => {
      clearInterval(timer);
      window.removeEventListener("console-update", listener);
    };
  }, [refresh, poll]);
  return { data: snapshot?.data, snapshot, error, loading, refresh };
}
export function useAction() {
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [success, setSuccess] = useState("");
  async function run(action: () => Promise<unknown>, message = "操作已受理") {
    if (busy) return;
    setBusy(true);
    setError("");
    setSuccess("");
    try {
      const result = await action();
      setSuccess(message);
      return result;
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return { busy, error, success, run };
}
