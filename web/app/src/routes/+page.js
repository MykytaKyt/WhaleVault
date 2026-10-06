import { guarded } from '#lib/api.js';
export const load = guarded(async ({ api }) => ({ topics: await api.get('/topics') }));
