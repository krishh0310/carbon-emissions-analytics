import { useQuery } from "@tanstack/react-query";
import { api } from "./api";

/** Current user (shared cache with the shell). `isAdmin` gates admin-only UI; the API enforces it independently. */
export function useMe() {
  const q = useQuery({ queryKey: ["me"], queryFn: () => api<{ id: number; email: string; role: string }>("/auth/me"), staleTime: 60_000 });
  return { ...q, isAdmin: q.data?.role === "admin" };
}
