import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Override when port 8000 is taken on the machine: FINSIGHT_API_URL=http://localhost:8360
const apiTarget = process.env.FINSIGHT_API_URL ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      // Dev server proxies the API so the browser sees a single origin and CORS
      // stays out of the way. In the Docker image, nginx does the same.
      "/api": {
        target: apiTarget,
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/api/, ""),
      },
    },
  },
});
