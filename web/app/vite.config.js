import adapter from '@sveltejs/adapter-static';
import { sveltekit } from '@sveltejs/kit/vite';
import tailwindcss from '@tailwindcss/vite';
import { defineConfig } from 'vite';

// The UI is a static SPA served by FastAPI (web/api/main.py): no SSR, no Node at runtime.
export default defineConfig({
	plugins: [
		tailwindcss(),
		sveltekit({
			adapter: adapter({ pages: 'dist', assets: 'dist', fallback: 'index.html', strict: false })
		})
	],
	server: {
		// npm run dev: API calls go to a locally running web/api (uvicorn on :8090)
		proxy: { '/api': 'http://127.0.0.1:8090' }
	}
});
