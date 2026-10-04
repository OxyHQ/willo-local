import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'
import reactNativeWeb from 'vite-plugin-react-native-web'

// Bloom is a React Native component library that runs on the web through
// react-native-web. This is the same setup the Oxy Vite apps use
// (oxy/packages/auth, console, test-app-vite):
//   - vite-plugin-react-native-web aliases react-native → react-native-web,
//     prefers `.web.*` files and defines the RN globals;
//   - @tailwindcss/vite generates the layout utilities Bloom's components emit
//     (see src/index.css for the Bloom theme import and the @source scan).
export default defineConfig(({ mode }) => ({
  plugins: [reactNativeWeb(), tailwindcss(), react()],
  define: {
    // vite-plugin-react-native-web pins __DEV__=false and NODE_ENV=production
    // unconditionally; re-assert the mode-aware values (user config wins).
    __DEV__: JSON.stringify(mode !== 'production'),
    'process.env.NODE_ENV': JSON.stringify(mode),
  },
}))
