<script>
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { FileText } from '@lucide/svelte';
	import { api } from '#lib/api.js';
	import { byDay, SOURCES } from '#lib/format.js';
	import { nav } from '#lib/state.svelte.js';
	import Empty from '#lib/ui/Empty.svelte';
	import LoadError from '#lib/ui/LoadError.svelte';
	import NoteCard from '#lib/ui/NoteCard.svelte';
	import Page from '#lib/ui/Page.svelte';
	import Skeleton from '#lib/ui/Skeleton.svelte';

	let { data } = $props();
	let extra = $state([]);
	let next = $state(null);
	let loading = $state(false);
	let sentinel = $state();

	$effect(() => {
		data;
		extra = [];
		next = data.notes?.next ?? null;
	});

	const params = $derived(page.url.searchParams);
	const notes = $derived([...(data.notes?.items ?? []), ...extra]);

	function setParam(key, value) {
		const u = new URL(page.url);
		if (value) u.searchParams.set(key, value);
		else u.searchParams.delete(key);
		goto(u, { keepFocus: true, noScroll: true });
	}

	async function more() {
		if (loading || !next) return;
		loading = true;
		const q = new URLSearchParams({ limit: '30', cursor: next });
		for (const k of ['topic', 'tag', 'source']) if (params.get(k)) q.set(k, params.get(k));
		const r = await api.get(`/notes?${q}`);
		extra = [...extra, ...r.items];
		next = r.next;
		loading = false;
	}

	$effect(() => {
		if (!sentinel) return;
		const io = new IntersectionObserver((e) => e[0].isIntersecting && more(), { rootMargin: '400px' });
		io.observe(sentinel);
		return () => io.disconnect();
	});
</script>

<Page title="Все заметки">
	<h1 class="t-page">Все заметки</h1>

	<div class="mt-5 grid grid-cols-2 gap-2 sm:grid-cols-3" role="group" aria-label="Фильтры">
		<select class="field py-2 text-[14px]" aria-label="Тема" value={params.get('topic') ?? ''} onchange={(e) => setParam('topic', e.currentTarget.value)}>
			<option value="">Все темы</option>
			{#each nav.topics as t (t.slug)}<option value={t.slug}>{t.emoji} {t.name}</option>{/each}
		</select>
		<select class="field py-2 text-[14px]" aria-label="Тег" value={params.get('tag') ?? ''} onchange={(e) => setParam('tag', e.currentTarget.value)}>
			<option value="">Все теги</option>
			{#each data.tags ?? [] as t (t.tag)}<option value={t.tag}>#{t.tag} ({t.n})</option>{/each}
		</select>
		<select class="field col-span-2 py-2 text-[14px] sm:col-span-1" aria-label="Источник" value={params.get('source') ?? ''} onchange={(e) => setParam('source', e.currentTarget.value)}>
			<option value="">Все источники</option>
			{#each Object.entries(SOURCES) as [k, label] (k)}<option value={k}>{label}</option>{/each}
		</select>
	</div>

	{#if data.error}
		<LoadError {data} />
	{:else if data.notes}
		{#each byDay(notes) as g (g.label)}
			<h2 class="t-small sticky top-14 z-10 mt-6 mb-1 bg-bg px-3 py-1 md:top-0">{g.label}</h2>
			{#each g.items as note (note.id)}<NoteCard {note} />{/each}
		{:else}
			<Empty icon={FileText} title="Ничего не нашлось">Попробуйте убрать фильтры.</Empty>
		{/each}
		<div bind:this={sentinel} class="h-4"></div>
		{#if loading}<Skeleton lines={2} />{/if}
	{:else}
		<Skeleton lines={6} />
	{/if}
</Page>
