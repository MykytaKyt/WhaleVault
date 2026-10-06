<script>
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { api } from '#lib/api.js';
	import NoteFeed from '#lib/components/NoteFeed.svelte';
	import { date } from '#lib/format.js';
	import { refreshSidebar, showToast, sidebar } from '#lib/state.svelte.js';

	let topic = $state(null);
	let error = $state('');
	let mergeInto = $state('');
	const id = $derived(Number(page.params.id));

	$effect(() => {
		topic = null;
		error = '';
		api.get(`/topics/${id}`).then((t) => (topic = t), (e) => (error = e.message));
	});

	async function save(field, value) {
		value = value.trim();
		if (!topic || value === (topic[field] ?? '') || (field === 'name' && !value)) return;
		try {
			topic = await api.patch(`/topics/${id}`, { [field]: value });
			refreshSidebar();
		} catch (e) {
			showToast(e.message.includes('merge') ? 'Тема с таким названием уже есть — объедините их' : e.message);
		}
	}

	async function merge() {
		const target = sidebar.topics.find((t) => t.id === Number(mergeInto));
		if (!target || !confirm(`Перенести все заметки из «${topic.name}» в «${target.name}» и удалить эту тему?`)) return;
		const r = await api.post(`/topics/${id}/merge`, { into_id: target.id });
		await refreshSidebar();
		showToast(`Перенесено заметок: ${r.moved}`);
		goto(`/topics/${target.id}`);
	}
	const enter = (e) => e.key === 'Enter' && (e.preventDefault(), e.currentTarget.blur());
</script>

<svelte:head><title>{topic?.name ?? 'Тема'} · WhaleVault</title></svelte:head>

{#if error}
	<p class="text-muted">Тема не найдена.</p>
{:else if topic}
	<div class="flex items-start gap-3">
		<input
			value={topic.emoji || '📁'}
			onblur={(e) => save('emoji', e.currentTarget.value)}
			onkeydown={enter}
			aria-label="Эмодзи"
			class="w-12 shrink-0 rounded-md bg-transparent text-[32px] leading-tight outline-none hover:bg-hover"
		/>
		<input
			value={topic.name}
			onblur={(e) => save('name', e.currentTarget.value)}
			onkeydown={enter}
			aria-label="Название темы"
			class="min-w-0 flex-1 rounded-md bg-transparent text-[32px] leading-tight font-bold outline-none hover:bg-hover"
		/>
	</div>
	<textarea
		value={topic.description}
		onblur={(e) => save('description', e.currentTarget.value)}
		placeholder="Описание темы"
		rows="1"
		class="mt-2 field-sizing-content w-full resize-none rounded-md bg-transparent text-muted outline-none placeholder:text-faint hover:bg-hover"
	></textarea>

	<dl class="mt-3 grid grid-cols-[120px_1fr] gap-y-1 border-b border-line pb-4 text-[14px]">
		<dt class="text-muted">Заметок</dt>
		<dd>{topic.notes_count}</dd>
		<dt class="text-muted">Обновлена</dt>
		<dd>{date(topic.updated_at)}</dd>
		<dt class="text-muted">Объединить</dt>
		<dd class="flex gap-2">
			<select bind:value={mergeInto} class="rounded bg-field px-1 text-[14px] outline-none">
				<option value="">с темой…</option>
				{#each sidebar.topics.filter((t) => t.id !== id) as t (t.id)}
					<option value={String(t.id)}>{t.emoji} {t.name}</option>
				{/each}
			</select>
			{#if mergeInto}<button class="text-accent" onclick={merge}>Перенести заметки</button>{/if}
		</dd>
	</dl>

	{#if topic.overview}
		<div class="prose-note mt-6">{topic.overview}</div>
	{:else}
		<p class="mt-6 text-[14px] text-faint">Обзор темы появится после ночной уборки (этап 6).</p>
	{/if}

	<NoteFeed topicId={id} />
{/if}
