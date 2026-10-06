// App-wide reactive state (Svelte 5 runes).
import { api } from './api.js';

export const session = $state({ authed: null }); // null = checking, false = login screen

export const nav = $state({ topics: [], open: false });

export async function refreshTopics() {
	try {
		nav.topics = await api.get('/topics');
	} catch {}
}

export const palette = $state({ open: false, query: '' });

export function openPalette(query = '') {
	palette.query = query;
	palette.open = true;
}

// One toast at a time, with an optional action (e.g. "Отменить" for 10 seconds after a delete)
export const toast = $state({ text: '', action: null, actionLabel: '', tone: 'info', id: 0 });
let timer;
export function showToast(text, { action = null, actionLabel = '', ms = 4000, tone = 'info' } = {}) {
	clearTimeout(timer);
	Object.assign(toast, { text, action, actionLabel, tone, id: toast.id + 1 });
	timer = setTimeout(() => (toast.text = ''), ms);
}
export function hideToast() {
	clearTimeout(timer);
	toast.text = '';
}

// Per-browser preferences (Настройки)
function readPref(key, fallback) {
	try {
		return localStorage.getItem(key) ?? fallback;
	} catch {
		return fallback;
	}
}
export const prefs = $state({ theme: readPref('theme', 'system'), showInbox: readPref('showInbox', '1') === '1' });

export function setPref(key, value) {
	prefs[key] = value;
	try {
		localStorage.setItem(key, typeof value === 'boolean' ? (value ? '1' : '0') : value);
	} catch {}
	if (key === 'theme') applyTheme(value);
}

export function applyTheme(theme) {
	if (theme === 'system') document.documentElement.removeAttribute('data-theme');
	else document.documentElement.dataset.theme = theme;
}
