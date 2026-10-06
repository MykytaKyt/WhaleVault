<script>
	import { page } from '$app/state';
	import { palette, sidebar } from '#lib/state.svelte.js';

	const links = [
		{ href: '/', icon: '📝', label: 'Все заметки' },
		{ href: '/inbox', icon: '📥', label: 'Входящие', count: () => sidebar.inbox },
		{ href: '/tasks', icon: '✅', label: 'Задачи', count: () => sidebar.open_tasks },
		{ href: '/entities', icon: '👤', label: 'Сущности' },
		{ href: '/ask', icon: '💬', label: 'Спросить' }
	];
	const active = (href) => (href === '/' ? page.url.pathname === '/' : page.url.pathname.startsWith(href));
	const close = () => (sidebar.open = false);
</script>

<!-- On phones the sidebar slides over the content -->
{#if sidebar.open}
	<button class="fixed inset-0 z-30 bg-black/30 md:hidden" aria-label="Закрыть меню" onclick={close}></button>
{/if}
<aside
	class="fixed inset-y-0 left-0 z-40 flex w-[260px] flex-col bg-side text-[14px] transition-transform md:sticky md:top-0 md:h-screen md:translate-x-0 {sidebar.open
		? 'translate-x-0'
		: '-translate-x-full'}"
>
	<div class="flex items-center gap-2 px-4 pt-4 pb-2 font-semibold">
		<span class="text-lg">🐋</span> WhaleVault
	</div>
	<button
		class="mx-2 mb-2 flex items-center gap-2 rounded-md px-2 py-1 text-left text-muted hover:bg-hover"
		onclick={() => {
			palette.open = true;
			close();
		}}
	>
		<span>🔍</span> Поиск <span class="ml-auto text-xs text-faint">Ctrl K</span>
	</button>
	<nav class="px-2">
		{#each links as l (l.href)}
			<a
				href={l.href}
				onclick={close}
				class="flex items-center gap-2 rounded-md px-2 py-1 hover:bg-hover {active(l.href) ? 'bg-hover font-medium' : 'text-muted'}"
			>
				<span class="w-5 text-center">{l.icon}</span>
				{l.label}
				{#if l.count && l.count()}<span class="ml-auto text-xs text-faint">{l.count()}</span>{/if}
			</a>
		{/each}
	</nav>
	<div class="mt-5 px-4 pb-1 text-xs font-medium text-faint">Темы</div>
	<nav class="min-h-0 flex-1 overflow-y-auto px-2 pb-4">
		{#each sidebar.topics as t (t.id)}
			<a
				href="/topics/{t.id}"
				onclick={close}
				class="flex items-center gap-2 rounded-md px-2 py-1 hover:bg-hover {page.url.pathname === `/topics/${t.id}`
					? 'bg-hover font-medium'
					: 'text-muted'}"
			>
				<span class="w-5 text-center">{t.emoji || '📁'}</span>
				<span class="truncate">{t.name}</span>
				<span class="ml-auto text-xs text-faint">{t.notes_count}</span>
			</a>
		{:else}
			<p class="px-2 text-faint">Пока пусто</p>
		{/each}
	</nav>
</aside>
