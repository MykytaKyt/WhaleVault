import { redirect } from '@sveltejs/kit';
import { guarded } from '#lib/api.js';

export const load = guarded(async ({ api, params, url }) => {
	const topic = await api.get(`/topics/${params.slug}`);
	if (topic.redirect) redirect(308, `/t/${topic.redirect}${url.search}`); // merged topic: old links keep working
	const q = new URLSearchParams({ limit: '30' });
	if (url.searchParams.get('tag')) q.set('tag', url.searchParams.get('tag'));
	if (url.searchParams.get('sort') === 'old') q.set('sort', 'old');
	return { topic, notes: await api.get(`/topics/${params.slug}/notes?${q}`) };
});
