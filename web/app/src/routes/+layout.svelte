<script>
	import '../app.css';
	import { onMount } from 'svelte';
	import { api } from '#lib/api.js';
	import Login from '#lib/components/Login.svelte';
	import Palette from '#lib/components/Palette.svelte';
	import Sidebar from '#lib/components/Sidebar.svelte';
	import Toast from '#lib/components/Toast.svelte';
	import { refreshSidebar, session, sidebar } from '#lib/state.svelte.js';

	let { children } = $props();

	onMount(async () => {
		try {
			await api.get('/me');
			session.authed = true;
		} catch {
			session.authed = false;
		}
	});

	$effect(() => {
		if (session.authed) refreshSidebar();
	});
</script>

{#if session.authed === false}
	<Login />
{:else if session.authed}
	<div class="flex min-h-screen">
		<Sidebar />
		<main class="min-w-0 flex-1">
			<button
				class="sticky top-0 z-20 m-2 rounded-md bg-bg/80 px-2 py-1 text-xl backdrop-blur md:hidden"
				aria-label="Меню"
				onclick={() => (sidebar.open = true)}>☰</button
			>
			<div class="mx-auto max-w-[720px] px-5 pt-4 pb-24 md:px-6 md:pt-16">
				{@render children()}
			</div>
		</main>
	</div>
	<Palette />
	<Toast />
{/if}
