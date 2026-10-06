const dayFmt = new Intl.DateTimeFormat('ru', { day: 'numeric', month: 'long' });
const dayYearFmt = new Intl.DateTimeFormat('ru', { day: 'numeric', month: 'long', year: 'numeric' });
const timeFmt = new Intl.DateTimeFormat('ru', { hour: '2-digit', minute: '2-digit' });
const shortFmt = new Intl.DateTimeFormat('ru', { day: 'numeric', month: 'short' });

const parse = (iso) => new Date(iso.length === 10 ? `${iso}T00:00:00` : iso);

function sameDay(a, b) {
	return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

/** "Сегодня" / "Вчера" / "Завтра" / "3 октября" / "3 октября 2025" */
export function dayLabel(iso) {
	if (!iso) return '';
	const d = parse(iso);
	const now = new Date();
	const shift = (n) => {
		const x = new Date(now);
		x.setDate(now.getDate() + n);
		return x;
	};
	if (sameDay(d, now)) return 'Сегодня';
	if (sameDay(d, shift(-1))) return 'Вчера';
	if (sameDay(d, shift(1))) return 'Завтра';
	return d.getFullYear() === now.getFullYear() ? dayFmt.format(d) : dayYearFmt.format(d);
}

export const time = (iso) => (iso ? timeFmt.format(parse(iso)) : '');
export const date = (iso) => (iso ? dayYearFmt.format(parse(iso)) : '');
export const shortDate = (iso) => (iso ? shortFmt.format(parse(iso)) : '');

/** "5 мин назад" / "3 ч назад" / day label */
export function ago(iso) {
	if (!iso) return '';
	const s = (Date.now() - parse(iso).getTime()) / 1000;
	if (s < 60) return 'только что';
	if (s < 3600) return `${Math.floor(s / 60)} мин назад`;
	if (s < 86400) return `${Math.floor(s / 3600)} ч назад`;
	return dayLabel(iso);
}

/** Task due: "YYYY-MM-DD" or "YYYY-MM-DDTHH:MM", local time */
export function due(s) {
	if (!s) return '';
	const label = dayLabel(s.slice(0, 10));
	return s.length > 10 ? `${label}, ${s.slice(11, 16)}` : label;
}

export function plural(n, one, few, many) {
	const m10 = n % 10,
		m100 = n % 100;
	const w = m10 === 1 && m100 !== 11 ? one : m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14) ? few : many;
	return `${n} ${w}`;
}

export const SOURCES = { text: 'Текст', voice: 'Голосовое', link: 'Ссылка', photo: 'Фото', forward: 'Пересланное' };
export const KINDS = { person: 'Люди', car: 'Машины', project: 'Проекты', place: 'Места', other: 'Другое' };

/** Group items with created_at by day label, keeping order */
export function byDay(items, key = 'created_at') {
	const groups = [];
	for (const it of items) {
		const label = dayLabel(it[key]);
		if (!groups.length || groups.at(-1).label !== label) groups.push({ label, items: [] });
		groups.at(-1).items.push(it);
	}
	return groups;
}

export function bytes(n) {
	if (n == null) return '—';
	const u = ['Б', 'КБ', 'МБ', 'ГБ', 'ТБ'];
	let i = 0;
	while (n >= 1024 && i < u.length - 1) {
		n /= 1024;
		i++;
	}
	return `${n.toFixed(n < 10 && i ? 1 : 0)} ${u[i]}`;
}

export const pct = (x, digits = 0) => (x == null ? '—' : `${(x * 100).toFixed(digits)}%`);
export const num = (x, digits = 0) => (x == null ? '—' : x.toFixed(digits));
