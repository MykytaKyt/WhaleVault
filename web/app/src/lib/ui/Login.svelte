<script>
	import { invalidateAll } from '$app/navigation';
	import { api } from '#lib/api.js';
	import { session } from '#lib/state.svelte.js';

	let password = $state('');
	let error = $state('');
	let busy = $state(false);

	async function submit(e) {
		e.preventDefault();
		busy = true;
		error = '';
		try {
			await api.post('/auth/login', { password });
			session.authed = true;
			await invalidateAll();
		} catch (err) {
			error = err.message;
		} finally {
			busy = false;
		}
	}
</script>

<main class="flex min-h-dvh items-center justify-center px-4">
	<form onsubmit={submit} class="w-full max-w-xs">
		<div class="mb-4 text-center text-4xl" aria-hidden="true">🐋</div>
		<h1 class="mb-6 text-center text-xl font-semibold">WhaleVault</h1>
		<label for="password" class="t-small mb-1 block">Пароль</label>
		<!-- svelte-ignore a11y_autofocus -->
		<input id="password" type="password" bind:value={password} autocomplete="current-password" autofocus class="field" />
		{#if error}<p class="mt-2 text-[14px] text-error" role="alert">{error}</p>{/if}
		<button disabled={busy || !password} class="btn btn-primary mt-4 w-full">Войти</button>
	</form>
</main>
