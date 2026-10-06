import { guarded } from '#lib/api.js';

export const load = guarded(async ({ api, url }) => {
	const q = new URLSearchParams({ limit: '30' });
	for (const k of ['topic', 'tag', 'source']) if (url.searchParams.get(k)) q.set(k, url.searchParams.get(k));
	const [notes, tags] = await Promise.all([api.get(`/notes?${q}`), api.get('/tags')]);
	return { notes, tags };
});
