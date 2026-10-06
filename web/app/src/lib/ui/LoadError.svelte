<script>
	import { CircleAlert } from '@lucide/svelte';
	import Empty from './Empty.svelte';
	let { data, what = 'Страница' } = $props();
</script>

{#if data.code === 404}
	<Empty icon={CircleAlert} title="{what} не найдена">Возможно, её удалили или объединили. <a class="text-accent" href="/">К темам</a></Empty>
{:else}
	<Empty icon={CircleAlert} tone="error" title="Не удалось загрузить">{data.error}</Empty>
{/if}
