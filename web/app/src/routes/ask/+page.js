import { guarded } from '#lib/api.js';

export const load = guarded(async ({ api, url }) => {
	const id = url.searchParams.get('id');
	const [history, current] = await Promise.all([api.get('/ask/history'), id ? api.get(`/ask/${id}`) : null]);
	return { history, current };
});
