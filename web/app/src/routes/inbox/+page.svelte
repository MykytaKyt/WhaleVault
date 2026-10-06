<script>
	import { api } from '#lib/api.js';
	import { dayLabel } from '#lib/format.js';
	import { refreshSidebar, showToast } from '#lib/state.svelte.js';

	let data = $state(null);
	const load = async () => {
		data = await api.get('/inbox');
		refreshSidebar();
	};
	load();

	async function reprocess(n) {
		await api.post(`/notes/${n.id}/reprocess`);
		showToast('Отправлено на разбор: бот возьмёт заметку в течение 30 секунд');
		load();
	}
	async function remove(n) {
		await api.del(`/notes/${n.id}`);
		showToast('Удалено', {
			ms: 10000,
			actionLabel: 'Отменить',
			action: async () => {
				await api.post(`/notes/${n.id}/restore`);
				load();
			}
		});
		load();
	}
	async function merge(d) {
		await api.post(`/notes/${d.b}/merge`, { target_id: d.a });
		showToast(`#${d.b} объединена с #${d.a}`);
		load();
	}
	async function dismiss(d) {
		await api.post('/duplicates/dismiss', { a: d.a, b: d.b });
		load();
	}
</script>

<svelte:head><title>Входящие · WhaleVault</title></svelte:head>
<h1 class="text-[32px] leading-tight font-bold">Входящие</h1>
<p class="mt-1 text-muted">Что не удалось разобрать, и возможные дубли</p>

{#if data}
	{#if !data.failed.length && !data.duplicates.length}
		<p class="mt-8 text-muted">📭 Всё разобрано.</p>
	{/if}

	{#if data.failed.length}
		<h2 class="mt-8 mb-1 px-2 text-[13px] font-medium text-faint">Не удалось разобрать</h2>
		{#each data.failed as n (n.id)}
			<div class="rounded-md px-2 py-2 hover:bg-hover">
				<div class="line-clamp-3 text-[15px]">{n.raw_text}</div>
				<div class="mt-1 flex flex-wrap gap-x-4 text-[13px] text-muted">
					<span>{dayLabel(n.created_at)}</span>
					{#if n.error}<span class="truncate text-faint" title={n.error}>{n.error}</span>{/if}
					<button class="text-accent" onclick={() => reprocess(n)}>Переразобрать</button>
					<button class="hover:text-danger" onclick={() => remove(n)}>Удалить</button>
				</div>
			</div>
		{/each}
	{/if}

	{#if data.duplicates.length}
		<h2 class="mt-8 mb-1 px-2 text-[13px] font-medium text-faint">Возможные дубли</h2>
		{#each data.duplicates as d (`${d.a}-${d.b}`)}
			<div class="rounded-md px-2 py-2 hover:bg-hover">
				<div class="text-[15px]">
					<a href="/notes/{d.a}" class="hover:underline">{d.a_title || `#${d.a}`}</a>
					<span class="text-faint"> ≈ </span>
					<a href="/notes/{d.b}" class="hover:underline">{d.b_title || `#${d.b}`}</a>
				</div>
				<div class="mt-1 flex gap-4 text-[13px] text-muted">
					<span>сходство {Math.round(d.score * 100)}%</span>
					<button class="text-accent" onclick={() => merge(d)}>Объединить</button>
					<button class="hover:text-fg" onclick={() => dismiss(d)}>Это разные</button>
				</div>
			</div>
		{/each}
	{/if}
{/if}
