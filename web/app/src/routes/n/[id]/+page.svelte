<script>
	import { goto, invalidateAll } from '$app/navigation';
	import {
		Calendar, Folder, Forward, Image, Link, Mic, RotateCcw, Tag, Trash2, Type, CircleAlert
	} from '@lucide/svelte';
	import { api } from '#lib/api.js';
	import { date, due, SOURCES, time } from '#lib/format.js';
	import { nav, refreshTopics, showToast } from '#lib/state.svelte.js';
	import LoadError from '#lib/ui/LoadError.svelte';
	import Menu from '#lib/ui/Menu.svelte';
	import Page from '#lib/ui/Page.svelte';
	import Property from '#lib/ui/Property.svelte';

	let { data } = $props();
	const n = $derived(data.note);
	const SOURCE_ICONS = { text: Type, voice: Mic, link: Link, photo: Image, forward: Forward };

	let editing = $state(false);
	let draft = $state('');
	let original = $state(false);
	let tagInput = $state('');
	let topicSelect = $state();
	let tagField = $state();

	$effect(() => {
		data;
		editing = false;
		original = false;
	});

	async function patch(body, message) {
		try {
			await api.patch(`/notes/${n.id}`, body);
			await invalidateAll();
			if (message) showToast(message);
		} catch (e) {
			showToast(e.message, { tone: 'error' });
		}
	}

	function saveTitle(e) {
		const title = e.currentTarget.value.trim();
		if (title && title !== n.title) patch({ title });
	}
	async function saveText() {
		editing = false;
		if (draft !== (n.clean_text ?? n.raw_text)) await patch({ clean_text: draft }, 'Сохранено. Поиск и факты обновятся через несколько секунд.');
	}
	async function moveTo(e) {
		const topic_id = Number(e.currentTarget.value);
		if (topic_id && topic_id !== n.topic?.id) {
			await patch({ topic_id }, 'Тема изменена — модель учтёт это исправление');
			refreshTopics();
		}
	}
	function addTag(e) {
		e.preventDefault();
		const tag = tagInput.trim().replace(/^#/, '').toLowerCase();
		tagInput = '';
		if (tag && !n.tags.includes(tag)) patch({ tags: [...n.tags, tag] });
	}
	async function toggleTask(task) {
		await api.patch(`/tasks/${task.id}`, { status: task.status === 'done' ? 'open' : 'done' });
		invalidateAll();
	}
	async function remove() {
		const id = n.id;
		const back = n.topic ? `/t/${n.topic.slug}` : '/notes';
		await api.del(`/notes/${id}`);
		refreshTopics();
		showToast('Заметка удалена', {
			ms: 10000,
			actionLabel: 'Отменить',
			action: async () => {
				await api.post(`/notes/${id}/restore`);
				refreshTopics();
				goto(`/n/${id}`);
			}
		});
		goto(back);
	}
	async function reprocess() {
		await api.post(`/notes/${n.id}/reprocess`);
		showToast('Отправлено на разбор — бот возьмёт заметку в течение 30 секунд');
		invalidateAll();
	}

	const menu = $derived([
		{ label: 'Сменить тему', icon: Folder, onclick: () => topicSelect?.focus() },
		{ label: 'Добавить тег', icon: Tag, onclick: () => tagField?.focus() },
		{ label: 'Переразобрать', icon: RotateCcw, onclick: reprocess },
		{ label: 'Удалить', icon: Trash2, danger: true, onclick: remove }
	]);
	const STATUS = {
		queued: 'Заметка в очереди на разбор',
		processing: 'Модель разбирает заметку',
		failed: 'Не удалось разобрать',
		question: 'Бот принял это за вопрос — заметка не сохранена в базе',
		deleted: 'Заметка удалена'
	};
</script>

{#if data.error}
	<Page><LoadError {data} what="Заметка" /></Page>
{:else if n}
	<Page title={n.title || `Заметка #${n.id}`}>
		<div class="flex items-start gap-2">
			<h1 class="min-w-0 flex-1"><span class="sr-only">{n.title || `Заметка #${n.id}`}</span>
				<textarea
					value={n.title ?? ''}
					onblur={saveTitle}
					onkeydown={(e) => e.key === 'Enter' && (e.preventDefault(), e.currentTarget.blur())}
					rows="1"
					placeholder="Без заголовка"
					aria-label="Заголовок"
					class="t-page field-sizing-content w-full resize-none rounded-lg bg-transparent outline-none placeholder:text-muted hover:bg-hover focus:bg-hover"
				></textarea>
			</h1>
			<Menu items={menu} label="Действия с заметкой" />
		</div>
		<p class="t-small t-mono mt-1">#{n.id}</p>

		{#if n.status !== 'done'}
			<p class="mt-3 flex items-start gap-2 rounded-lg bg-field px-3 py-2 text-[14px]" role="status">
				<CircleAlert size={16} class="mt-1 shrink-0 {n.status === 'failed' ? 'text-error' : 'text-muted'}" aria-hidden="true" />
				<span>{STATUS[n.status] ?? n.status}{#if n.error}: <span class="text-muted">{n.error}</span>{/if}</span>
			</p>
		{/if}

		<!-- Properties, like Notion -->
		<div class="mt-4">
			<Property icon={Calendar} label="Дата">{date(n.created_at)}, {time(n.created_at)}</Property>
			<Property icon={Folder} label="Тема">
				<select
					bind:this={topicSelect}
					value={String(n.topic?.id ?? '')}
					onchange={moveTo}
					aria-label="Тема заметки"
					class="-ml-1 max-w-full rounded-md bg-transparent px-1 py-0.5 outline-none hover:bg-hover"
				>
					{#if !n.topic}<option value="">Без темы</option>{/if}
					{#each nav.topics as t (t.id)}<option value={String(t.id)}>{t.emoji} {t.name}</option>{/each}
					{#if n.topic && !nav.topics.some((t) => t.id === n.topic.id)}
						<option value={String(n.topic.id)}>{n.topic.emoji} {n.topic.name}</option>
					{/if}
				</select>
			</Property>
			<Property icon={Tag} label="Теги">
				<div class="flex flex-wrap items-center gap-1.5">
					{#each n.tags as tag (tag)}
						<span class="chip">
							<a href="/notes?tag={encodeURIComponent(tag)}">#{tag}</a>
							<button class="-my-1 -mr-1 inline-flex h-6 w-6 items-center justify-center rounded text-muted hover:text-error" aria-label="Убрать тег {tag}" onclick={() => patch({ tags: n.tags.filter((x) => x !== tag) })}>×</button>
						</span>
					{/each}
					<form onsubmit={addTag}>
						<input bind:this={tagField} bind:value={tagInput} placeholder="+ тег" aria-label="Новый тег" class="w-24 bg-transparent text-[14px] outline-none placeholder:text-muted" />
					</form>
				</div>
			</Property>
			<Property icon={SOURCE_ICONS[n.source] ?? Type} label="Источник">{SOURCES[n.source] ?? n.source}{#if n.context}<span class="text-muted"> · {n.context}</span>{/if}</Property>
		</div>

		<!-- Text: click to edit, saved on blur -->
		<section class="mt-6 border-t border-line pt-6" aria-label="Текст заметки">
			<div class="mb-3 flex justify-end">
				<div class="flex rounded-lg bg-chip p-0.5 text-[13px]" role="group" aria-label="Вид текста">
					<button class="rounded-md px-3 py-1 {original ? '' : 'bg-bg font-medium'}" aria-pressed={!original} onclick={() => (original = false)}>Обработанный</button>
					<button class="rounded-md px-3 py-1 {original ? 'bg-bg font-medium' : ''}" aria-pressed={original} onclick={() => ((original = true), (editing = false))}>Оригинал</button>
				</div>
			</div>
			{#if original}
				<div class="prose-plain">{n.raw_text}</div>
				{#each n.media as m (m.id)}
					<div class="mt-4">
						{#if m.mime.startsWith('audio/')}<audio controls src={m.url} class="w-full"></audio>
						{:else if m.mime.startsWith('image/')}<img src={m.url} alt="Фото из заметки" class="max-w-full rounded-lg" loading="lazy" />
						{:else}<a class="text-accent" href={m.url}>Файл ({m.mime})</a>{/if}
					</div>
				{/each}
			{:else if editing}
				<!-- svelte-ignore a11y_autofocus -->
				<textarea bind:value={draft} onblur={saveText} autofocus aria-label="Текст заметки" class="field field-sizing-content min-h-40 resize-none leading-[26px]"></textarea>
				<p class="t-small mt-1">Сохранится, когда уйдёте из поля</p>
			{:else}
				<button
					class="prose-plain -mx-2 block w-[calc(100%+16px)] cursor-text rounded-lg px-2 py-1 text-left hover:bg-hover"
					onclick={() => ((draft = n.clean_text ?? n.raw_text), (editing = true))}
					title="Нажмите, чтобы редактировать">{n.clean_text ?? n.raw_text}</button
				>
			{/if}
		</section>

		{#if n.tasks.length}
			<section class="mt-10" aria-label="Задачи">
				<h2 class="t-section mb-2">Задачи</h2>
				{#each n.tasks as task (task.id)}
					<label class="flex min-h-11 items-start gap-3 py-1">
						<input type="checkbox" checked={task.status === 'done'} onchange={() => toggleTask(task)} class="mt-1.5 h-4 w-4 accent-[var(--accent)]" />
						<span class={task.status === 'done' ? 'text-muted line-through' : ''}>
							{task.text}{#if task.due_at}<span class="t-small ml-2">{due(task.due_at)}</span>{/if}
						</span>
					</label>
				{/each}
			</section>
		{/if}

		{#if n.facts.length}
			<section class="mt-10" aria-label="Факты">
				<h2 class="t-section mb-2">Факты из этой заметки</h2>
				<ul class="space-y-1.5">
					{#each n.facts as f, i (i)}<li><span class="text-muted">{f.entity}:</span> {f.text}</li>{/each}
				</ul>
			</section>
		{/if}

		{#if n.related.length}
			<section class="mt-10" aria-label="Похожие заметки">
				<h2 class="t-section mb-2">Похожие заметки</h2>
				{#each n.related as r (r.id)}
					<a href="/n/{r.id}" class="flex min-h-11 items-center gap-3 rounded-lg px-3 hover:bg-hover">
						<span class="truncate">{r.title || `Заметка #${r.id}`}</span>
						<span class="t-small ml-auto shrink-0">{Math.round(r.score * 100)}%</span>
					</a>
				{/each}
			</section>
		{/if}
	</Page>
{/if}
