/** @type {import("tailwindcss").Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        ink: {
          950: '#070b14',
        },
      },
      boxShadow: {
        glow: '0 0 40px rgba(56, 189, 248, 0.12)',
      },
    },
  },
  plugins: [],
};
