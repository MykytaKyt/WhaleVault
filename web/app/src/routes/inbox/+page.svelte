<script>
	import { invalidateAll } from '$app/navigation';
	import { Inbox, LoaderCircle } from '@lucide/svelte';
	import { api } from '#lib/api.js';
	import { ago, dayLabel } from '#lib/format.js';
	import { refreshTopics, showToast } from '#lib/state.svelte.js';
	import Empty from '#lib/ui/Empty.svelte';
	import LoadError from '#lib/ui/LoadError.svelte';
	import Page from '#lib/ui/Page.svelte';

	let { data } = $props();
	const box = $derived(data.inbox);

	async function act(fn, message) {
		try {
			await fn();
			if (message) showToast(message);
			await invalidateAll();
			refreshTopics();
		} catch (e) {
			showToast(e.message, { tone: 'error' });
		}
	}
	const reprocess = (n) => act(() => api.post(`/notes/${n.id}/reprocess`), 'Отправлено на разбор — бот возьмёт заметку в течение 30 секунд');
	const remove = (n) =>
		act(async () => {
			await api.del(`/notes/${n.id}`);
			showToast('Удалено', { ms: 10000, actionLabel: 'Отменить', action: () => act(() => api.post(`/notes/${n.id}/restore`)) });
		});
	const dup = (d, action) => act(() => api.post(`/duplicates/${d.a}/${d.b}`, { action }), action === 'merge' ? `#${d.b} объединена с #${d.a}` : '');
</script>

<Page title="Входящие">
	<h1 class="t-page">Входящие</h1>
	<p class="t-small mt-1">То, что требует внимания: заметки в обработке, неразобранные и возможные дубли</p>

	{#if data.error}
		<LoadError {data} />
	{:else if box}
		{#if !box.processing.length && !box.failed.length && !box.duplicates.length}
			<Empty icon={Inbox} title="Всё разобрано">Новые заметки появятся здесь, пока модель их обрабатывает.</Empty>
		{/if}

		{#if box.processing.length}
			<h2 class="t-section mt-8 mb-2">В обработке</h2>
			{#each box.processing as n (n.id)}
				<div class="flex items-start gap-3 rounded-lg px-3 py-2">
					<LoaderCircle size={16} class="mt-1.5 shrink-0 animate-spin text-muted" aria-hidden="true" />
					<div class="min-w-0">
						<div class="line-clamp-2">{n.raw_text}</div>
						<div class="t-small">{n.status === 'processing' ? 'Модель разбирает' : 'В очереди'} · {ago(n.created_at)}</div>
					</div>
				</div>
			{/each}
		{/if}

		{#if box.failed.length}
			<h2 class="t-section mt-8 mb-2">Не удалось разобрать</h2>
			{#each box.failed as n (n.id)}
				<div class="rounded-lg px-3 py-3 hover:bg-hover">
					<a href="/n/{n.id}" class="line-clamp-3">{n.raw_text}</a>
					{#if n.error}<p class="t-small mt-1 text-error">Причина: {n.error}</p>{/if}
					<div class="mt-2 flex flex-wrap items-center gap-2">
						<span class="t-small mr-auto">{dayLabel(n.created_at)}</span>
						<button class="btn btn-secondary" onclick={() => reprocess(n)}>Переразобрать</button>
						<button class="btn btn-danger" onclick={() => remove(n)}>Удалить</button>
					</div>
				</div>
			{/each}
		{/if}

		{#if box.duplicates.length}
			<h2 class="t-section mt-8 mb-2">Возможные дубли</h2>
			{#each box.duplicates as d (`${d.a}-${d.b}`)}
				<div class="rounded-lg border border-line px-3 py-3 mb-2">
					<a href="/n/{d.a}" class="block font-medium hover:text-accent">{d.a_title || `#${d.a}`}</a>
					<a href="/n/{d.b}" class="block font-medium hover:text-accent">{d.b_title || `#${d.b}`}</a>
					<div class="mt-2 flex flex-wrap items-center gap-2">
						<span class="t-small mr-auto">сходство {Math.round(d.score * 100)}%</span>
						<button class="btn btn-secondary" onclick={() => dup(d, 'merge')}>Объединить</button>
						<button class="btn btn-ghost" onclick={() => dup(d, 'distinct')}>Разные</button>
					</div>
				</div>
			{/each}
		{/if}
	{/if}
</Page>
