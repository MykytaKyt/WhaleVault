<script>
	import { page } from '$app/state';
	import {
		Activity, FileText, Inbox, LayoutGrid, MessageCircle, Search, Settings, SquareCheck, Users, X
	} from '@lucide/svelte';
	import { nav, openPalette, prefs } from '#lib/state.svelte.js';

	// Order from the spec: Темы · Сущности · Задачи · Все заметки · Входящие · Спросить · Дашборд · Настройки
	const items = $derived(
		[
			{ href: '/', icon: LayoutGrid, label: 'Темы' },
			{ href: '/e', icon: Users, label: 'Сущности' },
			{ href: '/tasks', icon: SquareCheck, label: 'Задачи' },
			{ href: '/notes', icon: FileText, label: 'Все заметки' },
			prefs.showInbox && { href: '/inbox', icon: Inbox, label: 'Входящие' },
			{ href: '/ask', icon: MessageCircle, label: 'Спросить' },
			{ href: '/dash', icon: Activity, label: 'Дашборд' },
			{ href: '/settings', icon: Settings, label: 'Настройки' }
		].filter(Boolean)
	);
	const path = $derived(page.url.pathname);
	const active = (href) => (href === '/' ? path === '/' : path === href || path.startsWith(href + '/'));
	const close = () => (nav.open = false);
</script>

{#if nav.open}
	<button class="fixed inset-0 z-30 bg-black/40 md:hidden" aria-label="Закрыть меню" onclick={close}></button>
{/if}

<!-- Phone: drawer behind the hamburger. Tablet (768–1023): icons only. Desktop: 260 px. -->
<aside
	aria-label="Навигация"
	class="fixed inset-y-0 left-0 z-40 flex w-[280px] flex-col bg-panel transition-transform duration-150
		md:sticky md:top-0 md:h-dvh md:w-16 md:translate-x-0 lg:w-[260px]
		{nav.open ? 'translate-x-0' : '-translate-x-full'}"
>
	<div class="flex h-14 items-center gap-2 px-4 md:justify-center md:px-0 lg:justify-start lg:px-4">
		<span class="text-xl" aria-hidden="true">🐋</span>
		<span class="font-semibold md:hidden lg:inline">WhaleVault</span>
		<button class="icon-btn ml-auto md:hidden" aria-label="Закрыть меню" onclick={close}><X size={18} /></button>
	</div>

	<button
		class="mx-2 mb-2 flex min-h-11 items-center gap-2.5 rounded-lg px-3 text-[14px] text-muted hover:bg-hover md:min-h-10 md:justify-center md:px-0 lg:justify-start lg:px-3"
		title="Поиск (Ctrl K)"
		onclick={() => {
			close();
			openPalette();
		}}
	>
		<Search size={17} aria-hidden="true" />
		<span class="md:hidden lg:inline">Поиск</span>
		<kbd class="t-small ml-auto hidden font-sans lg:inline">Ctrl K</kbd>
	</button>

	<nav class="px-2">
		{#each items as item (item.href)}
			<a
				href={item.href}
				onclick={close}
				title={item.label}
				aria-current={active(item.href) ? 'page' : undefined}
				class="flex min-h-11 items-center gap-2.5 rounded-lg px-3 text-[14px] md:min-h-10 md:justify-center md:px-0 lg:justify-start lg:px-3
					{active(item.href) ? 'bg-accent-soft font-medium text-accent' : 'text-fg hover:bg-hover'}"
			>
				<item.icon size={17} aria-hidden="true" />
				<span class="md:hidden lg:inline">{item.label}</span>
			</a>
		{/each}
	</nav>

	<div class="t-small mt-5 px-5 pb-1 md:hidden lg:block">Темы</div>
	<nav aria-label="Темы" class="min-h-0 flex-1 overflow-y-auto px-2 pb-4 md:hidden lg:block">
		{#each nav.topics as t (t.slug)}
			<a
				href="/t/{t.slug}"
				onclick={close}
				aria-current={path === `/t/${t.slug}` ? 'page' : undefined}
				class="flex min-h-11 items-center gap-2.5 rounded-lg px-3 text-[14px] lg:min-h-9
					{path === `/t/${t.slug}` ? 'bg-accent-soft font-medium text-accent' : 'text-fg hover:bg-hover'}"
			>
				<span class="w-5 text-center" aria-hidden="true">{t.emoji || '📁'}</span>
				<span class="truncate">{t.name}</span>
				{#if t.new_today}<span class="h-1.5 w-1.5 shrink-0 rounded-full bg-accent" aria-label="есть новое"></span>{/if}
				<span class="t-small ml-auto">{t.notes_count}</span>
			</a>
		{/each}
	</nav>
</aside>
