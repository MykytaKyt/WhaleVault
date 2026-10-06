const dayFmt = new Intl.DateTimeFormat('ru', { day: 'numeric', month: 'long' });
const dayYearFmt = new Intl.DateTimeFormat('ru', { day: 'numeric', month: 'long', year: 'numeric' });
const timeFmt = new Intl.DateTimeFormat('ru', { hour: '2-digit', minute: '2-digit' });

export const parse = (iso) => new Date(iso);

function sameDay(a, b) {
	return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

/** "Сегодня" / "Вчера" / "Завтра" / "3 октября" / "3 октября 2025" */
export function dayLabel(iso) {
	const d = parse(iso);
	const now = new Date();
	const y = new Date(now);
	y.setDate(now.getDate() - 1);
	const t = new Date(now);
	t.setDate(now.getDate() + 1);
	if (sameDay(d, now)) return 'Сегодня';
	if (sameDay(d, y)) return 'Вчера';
	if (sameDay(d, t)) return 'Завтра';
	return d.getFullYear() === now.getFullYear() ? dayFmt.format(d) : dayYearFmt.format(d);
}

export const time = (iso) => timeFmt.format(parse(iso));
export const date = (iso) => (iso ? dayYearFmt.format(parse(iso)) : '');

/** Task due: "YYYY-MM-DD" or "YYYY-MM-DDTHH:MM", local time, no timezone */
export function due(s) {
	if (!s) return '';
	const [y, m, d] = s.slice(0, 10).split('-').map(Number);
	const label = dayLabel(new Date(y, m - 1, d).toISOString());
	return s.length > 10 ? `${label}, ${s.slice(11, 16)}` : label;
}

export const SOURCES = { text: 'Текст', voice: 'Голосовое', link: 'Ссылка', photo: 'Фото', forward: 'Пересланное' };
export const KINDS = { person: '👤 Люди', car: '🚗 Машины', project: '📌 Проекты', place: '📍 Места', other: '🔹 Другое' };

/** Group items with created_at by day label, keeping order */
export function byDay(items) {
	const groups = [];
	for (const it of items) {
		const label = dayLabel(it.created_at);
		if (!groups.length || groups.at(-1).label !== label) groups.push({ label, items: [] });
		groups.at(-1).items.push(it);
	}
	return groups;
}
