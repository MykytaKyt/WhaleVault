import { guarded } from '#lib/api.js';
export const load = guarded(async ({ api }) => ({ tasks: await api.get('/tasks') }));
