import { guarded } from '#lib/api.js';
export const load = guarded(async ({ api, params }) => ({ note: await api.get(`/notes/${params.id}`) }));
