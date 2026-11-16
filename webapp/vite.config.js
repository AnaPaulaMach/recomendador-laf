import { defineConfig } from "vite";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [tailwindcss()],
  build: {
    outDir: "recommender/static/dist",
    emptyOutDir: true,
    rollupOptions: {
      input: "assets/js/main.js",
      output: {
        entryFileNames: "app.js",
        assetFileNames: (assetInfo) =>
          assetInfo.name?.endsWith(".css") ? "app.css" : "assets/[name][extname]",
      },
    },
  },
});
