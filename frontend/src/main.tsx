import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { MutationCache, QueryCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Toaster, toast } from "sonner";
import App from "./App";
import "./index.css";

const onError = (e: Error) => toast.error(e.message);
const qc = new QueryClient({
  queryCache: new QueryCache({ onError }),
  mutationCache: new MutationCache({}),
  defaultOptions: { queries: { staleTime: 5 * 60_000, retry: 1, refetchOnWindowFocus: false } },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={qc}>
      <App />
      <Toaster theme="dark" richColors position="bottom-right" />
    </QueryClientProvider>
  </StrictMode>,
);
