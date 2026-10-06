<script>
	import { hideToast, toast } from '#lib/state.svelte.js';
</script>

{#if toast.text}
	<div
		class="fixed bottom-6 left-1/2 z-50 flex -translate-x-1/2 items-center gap-4 rounded-lg bg-[#2f2f2f] px-4 py-2.5 text-sm text-white shadow-lg"
	>
		{toast.text}
		{#if toast.action}
			<button
				class="font-medium text-[#529cca]"
				onclick={() => {
					toast.action();
					hideToast();
				}}>{toast.actionLabel}</button
			>
		{/if}
	</div>
{/if}
