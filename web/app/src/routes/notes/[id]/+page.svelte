<script>
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { api } from '#lib/api.js';
	import { date, due, SOURCES, time } from '#lib/format.js';
	import { refreshSidebar, showToast, sidebar } from '#lib/state.svelte.js';

	let note = $state(null);
	let error = $state('');
	let editing = $state(false);
	let draft = $state('');
	let showRaw = $state(false);
	let tagInput = $state('');
	const id = $derived(Number(page.params.id));

	$effect(() => {
		note = null;
		error = '';
		editing = false;
		showRaw = false;
		api.get(`/notes/${id}`).then((n) => (note = n), (e) => (error = e.message));
	});

	async function patch(body) {
		note = await api.patch(`/notes/${id}`, body);
	}

	async function saveTitle(e) {
		const title = e.currentTarget.value.trim();
		if (title && title !== note.title) await patch({ title });
	}

	async function saveText() {
		if (draft !== note.clean_text) await patch({ clean_text: draft });
		editing = false;
		showToast('Сохранено. Поиск обновится через несколько секунд.');
	}

	async function moveTo(e) {
		const topic_id = Number(e.currentTarget.value);
		if (!topic_id || topic_id === note.topic?.id) return;
		await patch({ topic_id });
		refreshSidebar();
		showToast('Тема изменена. Бот учтёт это исправление.');
	}

	async function addTag(e) {
		e.preventDefault();
		const tag = tagInput.trim().replace(/^#/, '').toLowerCase();
		if (tag && !note.tags.includes(tag)) await patch({ tags: [...note.tags, tag] });
		tagInput = '';
	}

	async function toggleTask(t) {
		await api.patch(`/tasks/${t.id}`, { status: t.status === 'done' ? 'open' : 'done' });
		note = await api.get(`/notes/${id}`);
		refreshSidebar();
	}

	async function remove() {
		await api.del(`/notes/${id}`);
		refreshSidebar();
		const back = note.topic ? `/topics/${note.topic.id}` : '/';
		showToast('Заметка удалена', {
			ms: 10000,
			actionLabel: 'Отменить',
			action: async () => {
				await api.post(`/notes/${id}/restore`);
				refreshSidebar();
				goto(`/notes/${id}`);
			}
		});
		goto(back);
	}
</script>

<svelte:head><title>{note?.title ?? 'Заметка'} · WhaleVault</title></svelte:head>

{#if error}
	<p class="text-muted">Заметка не найдена.</p>
{:else if note}
	<textarea
		value={note.title ?? ''}
		onblur={saveTitle}
		onkeydown={(e) => e.key === 'Enter' && (e.preventDefault(), e.currentTarget.blur())}
		rows="1"
		placeholder="Без заголовка"
		aria-label="Заголовок"
		class="field-sizing-content w-full resize-none rounded-md bg-transparent text-[32px] leading-tight font-bold outline-none placeholder:text-faint hover:bg-hover"
	></textarea>

	{#if note.status !== 'done'}
		<p class="mt-2 rounded-md bg-field px-3 py-2 text-[14px] text-muted">
			{note.status === 'deleted' ? '🗑 Заметка удалена' : note.status === 'failed' ? '⚠️ Не удалось разобрать' : `Статус: ${note.status}`}
		</p>
	{/if}

	<!-- Properties block, like Notion -->
	<dl class="mt-4 grid grid-cols-[120px_1fr] items-center gap-y-1.5 text-[14px]">
		<dt class="text-muted">Создана</dt>
		<dd>{date(note.created_at)}, {time(note.created_at)}</dd>
		<dt class="text-muted">Тема</dt>
		<dd>
			<select value={String(note.topic?.id ?? '')} onchange={moveTo} class="-ml-1 rounded bg-transparent px-1 outline-none hover:bg-hover">
				{#if !note.topic}<option value="">—</option>{/if}
				{#each sidebar.topics as t (t.id)}<option value={String(t.id)}>{t.emoji} {t.name}</option>{/each}
				{#if note.topic && !sidebar.topics.some((t) => t.id === note.topic.id)}
					<option value={String(note.topic.id)}>{note.topic.emoji} {note.topic.name}</option>
				{/if}
			</select>
		</dd>
		<dt class="text-muted">Теги</dt>
		<dd class="flex flex-wrap items-center gap-1.5">
			{#each note.tags as tag (tag)}
				<span class="group flex items-center rounded bg-chip px-1.5 text-[13px]">
					{tag}
					<button
						class="ml-1 hidden text-faint group-hover:inline"
						aria-label="Убрать тег {tag}"
						onclick={() => patch({ tags: note.tags.filter((t) => t !== tag) })}>×</button
					>
				</span>
			{/each}
			<form onsubmit={addTag}>
				<input bind:value={tagInput} placeholder="+ тег" class="w-20 bg-transparent text-[13px] outline-none placeholder:text-faint" />
			</form>
		</dd>
		<dt class="text-muted">Источник</dt>
		<dd>{SOURCES[note.source] ?? note.source}{note.context ? ` · ${note.context}` : ''}</dd>
	</dl>

	<div class="mt-6 border-t border-line pt-6">
		{#if editing}
			<!-- svelte-ignore a11y_autofocus -->
			<textarea
				bind:value={draft}
				autofocus
				class="field-sizing-content min-h-40 w-full resize-none rounded-md bg-field p-3 outline-none"
			></textarea>
			<div class="mt-2 flex gap-3 text-[14px]">
				<button class="rounded-md bg-accent px-3 py-1 font-medium text-white" onclick={saveText}>Сохранить</button>
				<button class="text-muted" onclick={() => (editing = false)}>Отмена</button>
			</div>
		{:else}
			<div class="prose-note">{showRaw ? note.raw_text : (note.clean_text ?? note.raw_text)}</div>
			<div class="mt-3 flex gap-4 text-[13px] text-faint">
				<button class="hover:text-fg" onclick={() => ((draft = note.clean_text ?? note.raw_text), (editing = true), (showRaw = false))}
					>Редактировать</button
				>
				<button class="hover:text-fg" onclick={() => (showRaw = !showRaw)}>{showRaw ? 'Показать обработанный' : 'Показать оригинал'}</button>
			</div>
		{/if}
	</div>

	{#if note.tasks.length}
		<h2 class="mt-10 mb-2 text-[13px] font-medium text-faint">Задачи</h2>
		{#each note.tasks as t (t.id)}
			<label class="flex items-start gap-2 py-1">
				<input type="checkbox" checked={t.status === 'done'} onchange={() => toggleTask(t)} class="mt-1.5 accent-accent" />
				<span class={t.status === 'done' ? 'text-faint line-through' : ''}>
					{t.text}{#if t.due_at}<span class="ml-2 text-[13px] text-muted">{due(t.due_at)}</span>{/if}
				</span>
			</label>
		{/each}
	{/if}

	{#if note.facts.length}
		<h2 class="mt-10 mb-2 text-[13px] font-medium text-faint">Факты из этой заметки</h2>
		<ul class="space-y-1 text-[15px]">
			{#each note.facts as f, i (i)}<li><span class="text-muted">{f.entity}:</span> {f.text}</li>{/each}
		</ul>
	{/if}

	{#if note.related.length}
		<h2 class="mt-10 mb-1 text-[13px] font-medium text-faint">Похожие заметки</h2>
		{#each note.related as r (r.id)}
			<a href="/notes/{r.id}" class="flex items-center gap-2 rounded-md px-2 py-1.5 hover:bg-hover">
				<span class="truncate">{r.title || `#${r.id}`}</span>
				<span class="ml-auto text-[12px] text-faint">{Math.round(r.score * 100)}%</span>
			</a>
		{/each}
	{/if}

	{#if note.status !== 'deleted'}
		<button class="mt-12 text-[13px] text-faint hover:text-danger" onclick={remove}>Удалить заметку</button>
	{/if}
{/if}
