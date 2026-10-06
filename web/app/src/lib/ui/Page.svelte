<script>
	/**
	 * Page frame: one text column up to 720 px; with `aside`, a 240 px properties column on the right
	 * on desktop (≥1024 px) that moves under the text on smaller screens.
	 */
	let { children, aside = null, title = '' } = $props();
</script>

<svelte:head>{#if title}<title>{title} · WhaleVault</title>{/if}</svelte:head>

{#if aside}
	<div class="mx-auto max-w-[720px] lg:grid lg:max-w-[1008px] lg:grid-cols-[minmax(0,720px)_240px] lg:gap-12">
		<div class="min-w-0">{@render children()}</div>
		<aside class="mt-10 border-t border-line pt-6 lg:mt-0 lg:border-0 lg:pt-1" aria-label="Свойства">
			<div class="lg:sticky lg:top-12">{@render aside()}</div>
		</aside>
	</div>
{:else}
	<div class="mx-auto max-w-[720px]">{@render children()}</div>
{/if}
