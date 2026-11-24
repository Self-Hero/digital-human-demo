import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

function normalizeBasePath(value: string | undefined): string {
  const trimmed = value?.trim() || "/";
  return `/${trimmed.replace(/^\/+|\/+$/g, "")}/`.replace(/^\/\/$/, "/");
}

function stripBasePath(path: string, basePath: string): string {
  if (basePath === "/") return path;
  const prefix = basePath.slice(0, -1);
  return path.startsWith(prefix) ? path.slice(prefix.length) || "/" : path;
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const base = normalizeBasePath(env.VITE_BASE_PATH);
  const apiPrefix = `${base}api`;
  const avatarPrefix = `${base}avatar-api`;
  const proxy = {
    [apiPrefix]: {
      target: "http://127.0.0.1:8001",
      changeOrigin: true,
      ws: true,
      rewrite: (path: string) => stripBasePath(path, base),
    },
    [avatarPrefix]: {
      target: "http://127.0.0.1:8010",
      changeOrigin: true,
      rewrite: (path: string) =>
        stripBasePath(path, base).replace(/^\/avatar-api/, ""),
    },
  };

  return {
    base,
    plugins: [react()],
    server: {
      host: "0.0.0.0",
      port: 5173,
      proxy,
    },
    preview: {
      host: "0.0.0.0",
      port: 4173,
      proxy,
    },
  };
});
