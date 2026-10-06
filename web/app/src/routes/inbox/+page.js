import { guarded } from '#lib/api.js';
export const load = guarded(async ({ api }) => ({ inbox: await api.get('/inbox') }));
