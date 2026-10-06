// App-wide reactive state (Svelte 5 runes).
import { api } from './api.js';

export const session = $state({ authed: null }); // null = checking, false = show login

export const sidebar = $state({ topics: [], inbox: 0, open_tasks: 0, notes: 0, open: false });

export async function refreshSidebar() {
	try {
		Object.assign(sidebar, await api.get('/sidebar'));
	} catch {}
}

export const palette = $state({ open: false });

// One toast at a time, with an optional action (e.g. "Отменить" for 10 seconds after a delete)
export const toast = $state({ text: '', action: null, actionLabel: '', id: 0 });
let timer;
export function showToast(text, { action = null, actionLabel = '', ms = 4000 } = {}) {
	clearTimeout(timer);
	Object.assign(toast, { text, action, actionLabel, id: toast.id + 1 });
	timer = setTimeout(() => (toast.text = ''), ms);
}
export function hideToast() {
	clearTimeout(timer);
	toast.text = '';
}
