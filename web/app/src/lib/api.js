// Client for web/api. Errors come as {error: {code, message}}; a 401 flips the app to the login screen.
import { session } from './state.svelte.js';

export class ApiError extends Error {
	constructor(code, message) {
		super(message);
		this.code = code;
	}
}

async function call(fetchFn, method, path, body) {
	let res;
	try {
		res = await fetchFn(`/api${path}`, {
			method,
			headers: body !== undefined ? { 'Content-Type': 'application/json' } : {},
			body: body !== undefined ? JSON.stringify(body) : undefined
		});
	} catch {
		throw new ApiError(0, 'Сервер не отвечает. Проверьте, что вы в домашней сети.');
	}
	if (res.status === 401 && !path.startsWith('/auth/login')) {
		session.authed = false;
		throw new ApiError(401, 'Нужно войти');
	}
	if (!res.ok) {
		let message = res.statusText;
		try {
			message = (await res.json()).error?.message ?? message;
		} catch {}
		throw new ApiError(res.status, message);
	}
	return res.json();
}

/** For components (window.fetch) */
export const api = {
	get: (path) => call(fetch, 'GET', path),
	post: (path, body = {}) => call(fetch, 'POST', path, body),
	patch: (path, body) => call(fetch, 'PATCH', path, body),
	del: (path) => call(fetch, 'DELETE', path)
};

/** For SvelteKit load functions: use their fetch so data is ready before the page shows */
export const loadApi = (fetchFn) => ({ get: (path) => call(fetchFn, 'GET', path) });

/** Poll a background job until it finishes; onUpdate gets every state */
export async function waitJob(job, onUpdate) {
	while (job && (job.status === 'queued' || job.status === 'running')) {
		onUpdate?.(job);
		await new Promise((r) => setTimeout(r, 1000));
		job = await api.get(`/jobs/${job.id}`);
	}
	onUpdate?.(job);
	return job;
}

/**
 * Wrap a load function: 401 → empty data (the layout shows the login screen),
 * other errors → {error, code} for the page to show an honest message.
 */
export function guarded(fn) {
	return async (event) => {
		try {
			return await fn({ ...event, api: loadApi(event.fetch) });
		} catch (e) {
			if (e.code === 401) return { unauthorized: true };
			return { error: e.message, code: e.code ?? 0 };
		}
	};
}
