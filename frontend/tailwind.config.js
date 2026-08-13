/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#080b11",
        panel: "#111725",
        edge: "#1f2a3d",
        accent: "#38bdf8",
        safe: "#4ade80",
        grey: "#fbbf24",
        distress: "#f87171",
        muted: "#64748b",
      },
      fontFamily: {
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
    },
  },
  plugins: [],
};
