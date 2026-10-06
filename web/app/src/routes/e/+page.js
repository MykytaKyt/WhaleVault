import { guarded } from '#lib/api.js';
export const load = guarded(async ({ api }) => ({ entities: await api.get('/entities') }));
