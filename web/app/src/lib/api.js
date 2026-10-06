// Thin client for web/api. A 401 anywhere flips the app to the login screen.
import { session } from './state.svelte.js';

async function call(method, path, body) {
	const res = await fetch(`/api${path}`, {
		method,
		headers: body !== undefined ? { 'Content-Type': 'application/json' } : {},
		body: body !== undefined ? JSON.stringify(body) : undefined
	});
	if (res.status === 401 && path !== '/login') {
		session.authed = false;
		throw new Error('login required');
	}
	if (!res.ok) {
		let detail = res.statusText;
		try {
			detail = (await res.json()).detail ?? detail;
		} catch {}
		throw new Error(detail);
	}
	return res.json();
}

export const api = {
	get: (path) => call('GET', path),
	post: (path, body = {}) => call('POST', path, body),
	patch: (path, body) => call('PATCH', path, body),
	del: (path) => call('DELETE', path)
};

/** POST /api/ask and read the SSE stream. handlers: { status, sources, token, done, error } */
export async function ask(question, handlers, signal) {
	const res = await fetch('/api/ask', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ question }),
		signal
	});
	if (res.status === 401) {
		session.authed = false;
		return;
	}
	const reader = res.body.getReader();
	const decoder = new TextDecoder();
	let buf = '';
	for (;;) {
		const { value, done } = await reader.read();
		if (done) break;
		buf += decoder.decode(value, { stream: true });
		let i;
		while ((i = buf.indexOf('\n\n')) >= 0) {
			const block = buf.slice(0, i);
			buf = buf.slice(i + 2);
			let event = 'message';
			let data = '';
			for (const line of block.split('\n')) {
				if (line.startsWith('event:')) event = line.slice(6).trim();
				else if (line.startsWith('data:')) data += line.slice(5).trim();
			}
			handlers[event]?.(data ? JSON.parse(data) : null);
		}
	}
}
