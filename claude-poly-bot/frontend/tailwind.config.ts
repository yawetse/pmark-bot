import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{js,ts,jsx,tsx,mdx}", "./components/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        // Banner / status colors used across the dashboard
        dry: { DEFAULT: "#94a3b8" },
        live: { DEFAULT: "#dc2626" },
      },
    },
  },
  plugins: [],
};

export default config;
