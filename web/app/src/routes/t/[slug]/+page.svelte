<script>
	import { goto, invalidateAll } from '$app/navigation';
	import { page } from '$app/state';
	import {
		ArrowDownUp, Calendar, FileText, GitMerge, Network, Pencil, RefreshCw, Scissors, TriangleAlert, Users
	} from '@lucide/svelte';
	import { api, waitJob } from '#lib/api.js';
	import { ago, byDay, plural } from '#lib/format.js';
	import { nav, refreshTopics, showToast } from '#lib/state.svelte.js';
	import Dialog from '#lib/ui/Dialog.svelte';
	import LoadError from '#lib/ui/LoadError.svelte';
	import Markdown from '#lib/ui/Markdown.svelte';
	import Menu from '#lib/ui/Menu.svelte';
	import NoteCard from '#lib/ui/NoteCard.svelte';
	import Page from '#lib/ui/Page.svelte';
	import Property from '#lib/ui/Property.svelte';

	let { data } = $props();
	const t = $derived(data.topic);

	let nameInput = $state();
	let job = $state(null); // running refresh/split job
	let merging = $state(false);
	let mergeTarget = $state('');
	let proposal = $state(null); // split proposal from the model
	let extra = $state([]); // notes loaded with "Показать ещё"
	let next = $state(null);

	$effect(() => {
		// New page data (other topic, filter, after invalidate): reset local state
		data;
		extra = [];
		next = data.notes?.next ?? null;
		if (data.topic?.job && !job) follow(data.topic.job);
	});

	const tag = $derived(page.url.searchParams.get('tag'));
	const sortOld = $derived(page.url.searchParams.get('sort') === 'old');

	function setParam(key, value) {
		const u = new URL(page.url);
		if (value) u.searchParams.set(key, value);
		else u.searchParams.delete(key);
		goto(u, { keepFocus: true, noScroll: true, replaceState: true });
	}

	async function save(field, value) {
		value = value.trim();
		if ((t[field] ?? '') === value || (field === 'name' && !value)) return;
		try {
			await api.patch(`/topics/${t.slug}`, { [field]: value });
			await Promise.all([invalidateAll(), refreshTopics()]);
		} catch (e) {
			showToast(e.message, { tone: 'error' });
		}
	}

	async function follow(j) {
		job = j;
		const done = await waitJob(j, (x) => (job = x));
		job = null;
		if (done.status === 'failed') {
			showToast(done.message || 'Не получилось', { tone: 'error', ms: 8000 });
		} else if (done.kind === 'split_topic') {
			proposal = done.result;
		} else {
			showToast('Сводка обновлена');
			await invalidateAll();
			refreshTopics();
		}
	}

	async function refresh() {
		follow(await api.post(`/topics/${t.slug}/refresh`));
	}
	async function split() {
		follow(await api.post(`/topics/${t.slug}/split`));
	}
	async function applySplit() {
		const r = await api.post(`/topics/${t.slug}/split/apply`, { groups: proposal.groups });
		proposal = null;
		showToast(`Создано тем: ${r.created.length}`);
		await Promise.all([invalidateAll(), refreshTopics()]);
	}
	async function merge() {
		const r = await api.post('/topics/merge', { source: t.slug, target: mergeTarget });
		merging = false;
		showToast(`Перенесено ${plural(r.moved, 'заметка', 'заметки', 'заметок')}`);
		await refreshTopics();
		goto(`/t/${r.target}`);
	}
	async function more() {
		const q = new URLSearchParams({ limit: '30', cursor: next });
		if (tag) q.set('tag', tag);
		if (sortOld) q.set('sort', 'old');
		const r = await api.get(`/topics/${t.slug}/notes?${q}`);
		extra = [...extra, ...r.items];
		next = r.next;
	}

	const notes = $derived([...(data.notes?.items ?? []), ...extra]);
	const enter = (e) => e.key === 'Enter' && (e.preventDefault(), e.currentTarget.blur());
	const menu = [
		{ label: 'Переименовать', icon: Pencil, onclick: () => nameInput?.focus() },
		{ label: 'Объединить с другой темой', icon: GitMerge, onclick: () => (merging = true) },
		{ label: 'Разделить (предложит модель)', icon: Scissors, onclick: split }
	];
</script>

{#if data.error}
	<Page><LoadError {data} what="Тема" /></Page>
{:else if t}
	<Page title={t.name}>
		{#snippet aside()}
			<h2 class="t-small mb-2 font-medium">Свойства</h2>
			<Property icon={FileText} label="Заметок">{t.notes_count}</Property>
			<Property icon={Calendar} label="Сводка">
				{#if t.overview_updated_at}{ago(t.overview_updated_at)}{#if t.overview_stale}<span class="badge badge-warn ml-1">устарела</span>{/if}{:else}<span class="text-muted">нет</span>{/if}
			</Property>
			{#if t.entities.length}
				<Property icon={Users} label="Сущности">
					<div class="flex flex-wrap gap-1">
						{#each t.entities as e (e.id)}<a class="chip" href="/e/{e.id}">{e.name}</a>{/each}
					</div>
				</Property>
			{/if}
			{#if t.neighbors.length}
				<Property icon={Network} label="Соседние">
					<div class="flex flex-col">
						{#each t.neighbors as n (n.slug)}<a class="truncate hover:text-accent" href="/t/{n.slug}">{n.emoji} {n.name}</a>{/each}
					</div>
				</Property>
			{/if}
		{/snippet}

		<!-- Header: emoji and name edit in place, saved on blur -->
		<div class="flex items-start gap-2">
			<input
				value={t.emoji || '📁'}
				onblur={(e) => save('emoji', e.currentTarget.value)}
				onkeydown={enter}
				aria-label="Эмодзи темы"
				class="h-10 w-11 shrink-0 rounded-lg bg-transparent text-center text-[28px] outline-none hover:bg-hover focus:bg-hover"
			/>
			<h1 class="min-w-0 flex-1"><span class="sr-only">{t.name}</span>
				<input
					bind:this={nameInput}
					value={t.name}
					onblur={(e) => save('name', e.currentTarget.value)}
					onkeydown={enter}
					aria-label="Название темы"
					class="t-page w-full rounded-lg bg-transparent outline-none hover:bg-hover focus:bg-hover"
				/>
			</h1>
			<Menu items={menu} label="Действия с темой" />
		</div>
		<textarea
			value={t.description}
			onblur={(e) => save('description', e.currentTarget.value)}
			placeholder="Описание темы (помогает модели раскладывать заметки)"
			rows="1"
			aria-label="Описание темы"
			class="mt-1 field-sizing-content w-full resize-none rounded-lg bg-transparent text-muted outline-none placeholder:text-muted/70 hover:bg-hover focus:bg-hover"
		></textarea>

		<!-- Summary -->
		<section class="mt-6 border-t border-line pt-6" aria-label="Сводка">
			<div class="mb-4 flex flex-wrap items-center gap-3">
				<button class="btn btn-secondary" disabled={!!job} onclick={refresh}>
					<RefreshCw size={15} class={job ? 'animate-spin' : ''} aria-hidden="true" />
					{job ? 'Обновляю…' : 'Обновить сводку сейчас'}
				</button>
				{#if job}
					<span class="t-small" role="status">{job.message || 'В очереди'}</span>
				{:else if t.overview_stale && t.has_overview}
					<span class="t-small flex items-center gap-1 text-warn"><TriangleAlert size={14} aria-hidden="true" />Есть заметки новее сводки</span>
				{/if}
			</div>
			{#if t.overview}
				<Markdown text={t.overview} />
			{:else}
				<p class="text-muted">
					Сводки ещё нет. Её пишет модель: ночью сама или сейчас по кнопке — это займёт до минуты.
				</p>
			{/if}
		</section>

		<!-- Notes of the topic -->
		<section class="mt-10" aria-label="Заметки темы">
			<div class="mb-3 flex items-center gap-2">
				<h2 class="t-section flex-1">Заметки</h2>
				<button class="btn btn-ghost" onclick={() => setParam('sort', sortOld ? '' : 'old')}>
					<ArrowDownUp size={15} aria-hidden="true" />{sortOld ? 'Сначала старые' : 'Сначала новые'}
				</button>
			</div>
			{#if t.tags.length}
				<div class="mb-3 flex flex-wrap gap-1.5" role="group" aria-label="Фильтр по тегу">
					{#if tag}<button class="chip" onclick={() => setParam('tag', '')}>Все</button>{/if}
					{#each t.tags.slice(0, 12) as x (x.tag)}
						<button class="chip {tag === x.tag ? 'chip-active' : ''}" aria-pressed={tag === x.tag} onclick={() => setParam('tag', tag === x.tag ? '' : x.tag)}>
							#{x.tag} <span class="text-muted">{x.n}</span>
						</button>
					{/each}
				</div>
			{/if}
			{#each byDay(notes) as g (g.label)}
				<h3 class="t-small mt-4 mb-1 px-3">{g.label}</h3>
				{#each g.items as note (note.id)}<NoteCard {note} showTopic={false} />{/each}
			{:else}
				<p class="px-3 text-muted">Нет заметок{tag ? ` с тегом #${tag}` : ''}.</p>
			{/each}
			{#if next}<button class="btn btn-ghost mt-2" onclick={more}>Показать ещё</button>{/if}
		</section>
	</Page>

	<Dialog bind:open={merging} title="Объединить с темой">
		<p class="t-small mb-3">Все заметки «{t.name}» переедут в выбранную тему, старая ссылка продолжит работать.</p>
		<select bind:value={mergeTarget} class="field" aria-label="Тема, в которую перенести">
			<option value="">Выберите тему…</option>
			{#each nav.topics.filter((x) => x.slug !== t.slug) as x (x.slug)}<option value={x.slug}>{x.emoji} {x.name}</option>{/each}
		</select>
		{#snippet actions()}
			<button class="btn btn-ghost" onclick={() => (merging = false)}>Отмена</button>
			<button class="btn btn-primary" disabled={!mergeTarget} onclick={merge}>Объединить</button>
		{/snippet}
	</Dialog>

	<Dialog open={!!proposal} title="Разделить тему">
		{#if proposal}
			<p class="t-small mb-3">{proposal.reason}</p>
			<ul class="max-h-[50vh] space-y-3 overflow-y-auto">
				{#each proposal.groups as g, i (i)}
					<li class="rounded-lg border border-line p-3">
						<div class="font-medium">{g.emoji} {g.name}</div>
						{#if g.description}<div class="t-small">{g.description}</div>{/if}
						<div class="t-small mt-1">{plural(g.note_ids.length, 'заметка', 'заметки', 'заметок')}</div>
					</li>
				{/each}
			</ul>
		{/if}
		{#snippet actions()}
			<button class="btn btn-ghost" onclick={() => (proposal = null)}>Оставить как есть</button>
			<button class="btn btn-primary" disabled={(proposal?.groups.length ?? 0) < 2} onclick={applySplit}>Разделить</button>
		{/snippet}
	</Dialog>
{/if}
