import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Bind every interface. Without this Vite may listen on IPv6 [::1] only,
    // and a browser that resolves "localhost" to 127.0.0.1 gets connection
    // refused — the page simply never loads on Windows.
    host: true,
    strictPort: true,
    proxy: {
      // Target explicit IPv4: the API binds 127.0.0.1, so a "localhost"
      // target here can resolve to ::1 and fail the proxy.
      "/api": { target: "http://127.0.0.1:8000", changeOrigin: true },
      "/health": { target: "http://127.0.0.1:8000", changeOrigin: true },
    },
  },
});
