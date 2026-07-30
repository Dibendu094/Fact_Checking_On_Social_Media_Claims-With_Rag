/** @type {import('tailwindcss').Config} */
// Kept minimal: all real styling is in src/styles/veris.css (custom classes,
// not Tailwind utilities). This just keeps @tailwind base/reset available.
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {},
  },
  plugins: [],
};
