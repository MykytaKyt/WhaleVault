import { guarded } from '#lib/api.js';

export const load = guarded(async ({ api, url }) => {
	const period = ['day', 'week', 'month'].includes(url.searchParams.get('p')) ? url.searchParams.get('p') : 'day';
	const [live, summary, events] = await Promise.all([
		api.get('/metrics/live'),
		api.get(`/metrics/summary?period=${period}`),
		api.get('/metrics/events?limit=50')
	]);
	return { period, live, summary, events };
});
