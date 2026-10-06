<script>
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
			await api.post('/login', { password });
			session.authed = true;
		} catch {
			error = 'Неверный пароль';
		} finally {
			busy = false;
		}
	}
</script>

<div class="flex min-h-screen items-center justify-center px-6">
	<form onsubmit={submit} class="w-full max-w-xs">
		<div class="mb-6 text-center text-3xl">🐋</div>
		<h1 class="mb-6 text-center text-xl font-semibold">WhaleVault</h1>
		<!-- svelte-ignore a11y_autofocus -->
		<input
			type="password"
			bind:value={password}
			placeholder="Пароль"
			autocomplete="current-password"
			autofocus
			class="w-full rounded-md bg-field px-3 py-2 text-[15px] outline-none ring-accent/40 placeholder:text-faint focus:ring-2"
		/>
		{#if error}<p class="mt-2 text-sm text-danger">{error}</p>{/if}
		<button
			disabled={busy || !password}
			class="mt-3 w-full rounded-md bg-accent px-3 py-2 text-[15px] font-medium text-white disabled:opacity-50"
		>
			Войти
		</button>
	</form>
</div>
