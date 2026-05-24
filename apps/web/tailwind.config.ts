import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#e7edf5",
        paper: "#070b10",
        panel: "#101721",
        panelAlt: "#151f2b",
        panelLift: "#1b2836",
        line: "#283648",
        muted: "#93a3b7",
        accent: "#67d8ef",
        accentSoft: "#123849",
        warning: "#d6a94d",
        success: "#55c58e",
        danger: "#ff6b70",
        sky: "#75bdf2"
      },
      boxShadow: {
        panel: "0 18px 44px rgba(0, 0, 0, 0.28)",
        insetLine: "inset 0 1px 0 rgba(255, 255, 255, 0.04)"
      }
    }
  },
  plugins: []
} satisfies Config;
