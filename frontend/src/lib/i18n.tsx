// English + Hindi UI labels. Technical terms (CO₂, MASE, P10/P90, GSDP, MinT, SHAP) intentionally stay English.
import { createContext, useContext } from "react";

const hi: Record<string, string> = {
  "India Map": "भारत मानचित्र",
  "Live Map": "लाइव मानचित्र",
  Methodology: "कार्यप्रणाली",
  "State Explorer": "राज्य विश्लेषण",
  Cities: "शहर",
  Insights: "अंतर्दृष्टि",
  "Model Lab": "मॉडल लैब",
  "Data Quality": "डेटा गुणवत्ता",
  Admin: "प्रशासन",
  "Sign in": "साइन इन",
  "Create account": "खाता बनाएँ",
  "Sign out": "साइन आउट",
  Email: "ईमेल",
  Password: "पासवर्ड",
  Year: "वर्ष",
  Metric: "माप",
  "Total emissions": "कुल उत्सर्जन",
  "Per capita": "प्रति व्यक्ति",
  "Carbon intensity": "कार्बन तीव्रता",
  State: "राज्य",
  Model: "मॉडल",
  History: "इतिहास",
  Forecast: "पूर्वानुमान",
  "Top drivers": "मुख्य कारक",
  "Feature importance": "फ़ीचर महत्व",
  "Decoupling leaderboard": "डीकपलिंग तालिका",
  "Carbon-intensity ranking": "कार्बन तीव्रता रैंकिंग",
  Watchlist: "निगरानी सूची",
  Leaderboard: "लीडरबोर्ड",
  "Coverage heatmap": "कवरेज हीटमैप",
  "Imputation report": "इम्प्यूटेशन रिपोर्ट",
  "Retrain models": "मॉडल पुनः प्रशिक्षित करें",
  Jobs: "कार्य",
  "Model registry": "मॉडल रजिस्ट्री",
  Confidence: "विश्वसनीयता",
  Estimated: "अनुमानित",
  "Click a state to drill down": "विवरण के लिए किसी राज्य पर क्लिक करें",
};

export type Lang = "en" | "hi";
export const LangCtx = createContext<{ lang: Lang; setLang: (l: Lang) => void }>({ lang: "en", setLang: () => {} });

export function useT() {
  const { lang } = useContext(LangCtx);
  return (s: string) => (lang === "hi" ? hi[s] ?? s : s);
}

/** Bilingual label: "English / हिन्दी" when Hindi is on. */
export function useBi() {
  const { lang } = useContext(LangCtx);
  return (s: string) => (lang === "hi" && hi[s] ? `${hi[s]} · ${s}` : s);
}
