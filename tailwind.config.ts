import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./src/app/**/*.{ts,tsx}",
    "./src/components/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        base: "#0b0e14",
        panel: "#11151f",
        edge: "#1e2433",
        ink: "#e6e9f0",
        dim: "#8b93a7",
        pos: "#34d399",
        neg: "#f87171",
        accent: "#7aa2f7",
        warn: "#fbbf24",
      },
      fontFamily: {
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
    },
  },
  plugins: [],
};
export default config;
