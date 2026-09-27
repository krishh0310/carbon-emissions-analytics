// Tiny API client: bearer auth, one-shot refresh-token rotation on 401, typed JSON.
const BASE = "/api/v1";
const KEY = "carbonscope.tokens";

type Tokens = { access_token: string; refresh_token: string };

export const auth = {
  get: (): Tokens | null => {
    try {
      return JSON.parse(localStorage.getItem(KEY) ?? "null");
    } catch {
      return null;
    }
  },
  set: (t: Tokens | null) => (t ? localStorage.setItem(KEY, JSON.stringify(t)) : localStorage.removeItem(KEY)),
};

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

let refreshing: Promise<boolean> | null = null;

async function tryRefresh(): Promise<boolean> {
  const t = auth.get();
  if (!t) return false;
  const r = await fetch(`${BASE}/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: t.refresh_token }),
  });
  if (!r.ok) {
    auth.set(null);
    return false;
  }
  auth.set(await r.json());
  return true;
}

export async function api<T = any>(path: string, init: RequestInit = {}, retry = true): Promise<T> {
  const t = auth.get();
  const r = await fetch(path.startsWith("/api/") ? path : `${BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(t ? { Authorization: `Bearer ${t.access_token}` } : {}), ...init.headers },
  });
  if (r.status === 401 && retry && t) {
    refreshing ??= tryRefresh().finally(() => (refreshing = null));
    if (await refreshing) return api<T>(path, init, false);
    window.dispatchEvent(new Event("carbonscope:logout"));
  }
  if (!r.ok) {
    const body = await r.json().catch(() => ({}));
    const msg = typeof body.detail === "string" ? body.detail : Array.isArray(body.detail) ? body.detail[0]?.msg : r.statusText;
    throw new ApiError(r.status, msg ?? "request failed");
  }
  return r.json();
}

export async function login(email: string, password: string, register = false) {
  if (register) await api("/auth/register", { method: "POST", body: JSON.stringify({ email, password }) }, false);
  auth.set(await api<Tokens>("/auth/login", { method: "POST", body: JSON.stringify({ email, password }) }, false));
}
