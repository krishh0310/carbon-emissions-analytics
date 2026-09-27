export const SECTORS = ["POWER", "TRANSPORT", "INDUSTRY", "BUILDINGS", "AGRICULTURE", "WASTE", "OTHER"] as const;
export type Sector = (typeof SECTORS)[number];
export const SECTOR_COLORS = ["#f59e0b", "#3b82f6", "#ef4444", "#14b8a6", "#84cc16", "#a855f7", "#94a3b8"];
export const SECTOR_LABEL: Record<string, string> = {
  POWER: "Power", TRANSPORT: "Transport", INDUSTRY: "Industry", BUILDINGS: "Buildings", AGRICULTURE: "Agriculture", WASTE: "Waste", OTHER: "Other",
};
export const SECTOR_HI: Record<string, string> = { POWER: "बिजली", TRANSPORT: "परिवहन", INDUSTRY: "उद्योग", BUILDINGS: "भवन", AGRICULTURE: "कृषि", WASTE: "अपशिष्ट", OTHER: "अन्य" };
export const colorOf = (s: string) => SECTOR_COLORS[SECTORS.indexOf(s as Sector)] ?? "#94a3b8";
export const GROUP_LABEL: Record<string, string> = {
  sector_history: "Own sector trend", state_total_history: "State total trend", economy: "Economy (GSDP)", demography: "Population & urbanisation",
  climate: "Climate (CDD/HDD, monsoon)", policy: "Policy calendar", sector_drivers: "Sector activity data",
};
// Admin-only model list (used in the admin console).
export const MODELS = ["tft", "seq2seq_attn", "lstm", "gru", "tcn", "deepar", "lightgbm", "ridge", "arima", "drift", "naive"];
