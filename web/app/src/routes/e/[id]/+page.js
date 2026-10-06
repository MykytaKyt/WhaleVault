import { guarded } from '#lib/api.js';
export const load = guarded(async ({ api, params }) => ({ entity: await api.get(`/entities/${params.id}`) }));
