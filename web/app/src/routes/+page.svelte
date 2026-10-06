<script>
	import NoteFeed from '#lib/components/NoteFeed.svelte';
	import { sidebar } from '#lib/state.svelte.js';
</script>

<svelte:head><title>Все заметки · WhaleVault</title></svelte:head>
<h1 class="text-[32px] leading-tight font-bold">Все заметки</h1>
<p class="mt-1 text-muted">{sidebar.notes} заметок · {sidebar.topics.length} тем</p>
<NoteFeed />
