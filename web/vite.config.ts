import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Relative base so the same build works on GitHub Pages
// (/financing_compiler/) and inside the Capacitor Android app.
export default defineConfig({
  base: './',
  plugins: [react()],
})
