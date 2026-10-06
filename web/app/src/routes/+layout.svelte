<script>
	import '../app.css';
	import { onMount } from 'svelte';
	import { api } from '#lib/api.js';
	import Login from '#lib/ui/Login.svelte';
	import MobileBar from '#lib/ui/MobileBar.svelte';
	import Palette from '#lib/ui/Palette.svelte';
	import Sidebar from '#lib/ui/Sidebar.svelte';
	import Toast from '#lib/ui/Toast.svelte';
	import { applyTheme, prefs, refreshTopics, session } from '#lib/state.svelte.js';

	let { children } = $props();

	onMount(async () => {
		applyTheme(prefs.theme);
		try {
			await api.get('/auth/me');
			session.authed = true;
		} catch {
			session.authed = false;
		}
	});

	$effect(() => {
		if (session.authed) refreshTopics();
	});
</script>

<a href="#main" class="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-50 focus:rounded focus:bg-bg focus:p-2">К содержимому</a>

{#if session.authed === false}
	<Login />
{:else if session.authed}
	<div class="md:flex">
		<Sidebar />
		<div class="min-w-0 flex-1">
			<MobileBar />
			<main id="main" class="px-4 pt-6 pb-24 md:px-8 md:pt-12">{@render children()}</main>
		</div>
	</div>
	<Palette />
	<Toast />
{/if}
