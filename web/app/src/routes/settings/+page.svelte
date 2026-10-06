<script>
	import { invalidateAll } from '$app/navigation';
	import { Download, LogOut, Monitor, Moon, RefreshCw, Sun } from '@lucide/svelte';
	import { api, waitJob } from '#lib/api.js';
	import { prefs, session, setPref, showToast } from '#lib/state.svelte.js';
	import Dialog from '#lib/ui/Dialog.svelte';
	import Toggle from '#lib/ui/Toggle.svelte';

	const THEMES = [
		['system', 'Как в системе', Monitor],
		['light', 'Светлая', Sun],
		['dark', 'Тёмная', Moon]
	];

	let current = $state('');
	let next = $state('');
	let repeat = $state('');
	let pwError = $state('');
	let pwBusy = $state(false);

	async function changePassword(e) {
		e.preventDefault();
		pwError = '';
		if (next.length < 8) return (pwError = 'Новый пароль — минимум 8 символов');
		if (next !== repeat) return (pwError = 'Пароли не совпадают');
		pwBusy = true;
		try {
			await api.post('/settings/password', { current, new: next });
			showToast('Пароль изменён, войдите заново');
			session.authed = false;
			await invalidateAll();
		} catch (err) {
			pwError = err.message;
		} finally {
			pwBusy = false;
		}
	}

	let confirmReindex = $state(false);
	let job = $state(null);
	async function reindex() {
		confirmReindex = false;
		try {
			const started = await api.post('/settings/reindex');
			job = await waitJob(started, (j) => (job = j));
			if (job.status === 'done') showToast('Индекс пересобран');
		} catch (err) {
			showToast(err.message, { tone: 'error' });
		}
	}
	const busy = $derived(job && (job.status === 'queued' || job.status === 'running'));

	async function logout() {
		await api.post('/auth/logout').catch(() => {});
		session.authed = false;
		await invalidateAll();
	}
</script>

<svelte:head><title>Настройки · WhaleVault</title></svelte:head>

<div class="mx-auto max-w-[720px]">
	<h1 class="t-page">Настройки</h1>

	<section class="mt-8" aria-labelledby="s-theme">
		<h2 id="s-theme" class="t-section mb-3">Тема</h2>
		<div class="flex flex-wrap gap-2" role="radiogroup" aria-label="Тема">
			{#each THEMES as [value, label, Icon] (value)}
				<button
					role="radio"
					aria-checked={prefs.theme === value}
					class="btn {prefs.theme === value ? 'btn-primary' : 'btn-secondary'}"
					onclick={() => setPref('theme', value)}><Icon size={16} aria-hidden="true" />{label}</button
				>
			{/each}
		</div>
	</section>

	<section class="mt-10" aria-labelledby="s-nav">
		<h2 id="s-nav" class="t-section mb-1">Меню</h2>
		<Toggle label="Показывать «Входящие» в меню" checked={prefs.showInbox} onchange={(v) => setPref('showInbox', v)} />
	</section>

	<section class="mt-10" aria-labelledby="s-pw">
		<h2 id="s-pw" class="t-section mb-3">Пароль</h2>
		<form class="grid max-w-sm gap-3" onsubmit={changePassword}>
			<label class="grid gap-1"><span class="t-small">Текущий пароль</span><input class="field" type="password" autocomplete="current-password" bind:value={current} required /></label>
			<label class="grid gap-1"><span class="t-small">Новый пароль</span><input class="field" type="password" autocomplete="new-password" minlength="8" bind:value={next} required /></label>
			<label class="grid gap-1"><span class="t-small">Ещё раз</span><input class="field" type="password" autocomplete="new-password" bind:value={repeat} required /></label>
			{#if pwError}<p class="text-[14px] text-error" role="alert">{pwError}</p>{/if}
			<div><button class="btn btn-primary" disabled={pwBusy}>Сменить пароль</button></div>
			<p class="t-small">После смены все устройства выйдут. WEB_PASSWORD в .env больше не используется.</p>
		</form>
	</section>

	<section class="mt-10" aria-labelledby="s-data">
		<h2 id="s-data" class="t-section mb-3">Данные</h2>
		<div class="flex flex-col gap-4">
			<div>
				<button class="btn btn-secondary" disabled={busy} onclick={() => (confirmReindex = true)}>
					<RefreshCw size={16} aria-hidden="true" class={busy ? 'animate-spin' : ''} />Пересобрать поисковый индекс
				</button>
				{#if job}
					<p class="t-small mt-1" aria-live="polite">
						{#if busy}{job.message || 'Идёт…'}{job.progress ? ` ${Math.round(job.progress * 100)}%` : ''}
						{:else if job.status === 'failed'}<span class="text-error">{job.message}</span>
						{:else}Готово{/if}
					</p>
				{/if}
			</div>
			<div>
				<a class="btn btn-secondary" href="/api/export" download><Download size={16} aria-hidden="true" />Скачать архив (база + медиа)</a>
			</div>
		</div>
	</section>

	<section class="mt-10" aria-labelledby="s-session">
		<h2 id="s-session" class="t-section mb-3">Сеанс</h2>
		<button class="btn btn-secondary" onclick={logout}><LogOut size={16} aria-hidden="true" />Выйти</button>
	</section>
</div>

<Dialog bind:open={confirmReindex} title="Пересобрать индекс?">
	<p>Все заметки заново пройдут через модель эмбеддингов. На 1000 заметок это несколько минут; бот продолжит работать.</p>
	{#snippet actions()}
		<button class="btn btn-ghost" onclick={() => (confirmReindex = false)}>Отмена</button>
		<button class="btn btn-primary" onclick={reindex}>Пересобрать</button>
	{/snippet}
</Dialog>
