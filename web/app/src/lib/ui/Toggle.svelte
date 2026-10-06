<script>
	let { checked = $bindable(false), label, onchange = () => {} } = $props();
</script>

<label class="flex min-h-11 cursor-pointer items-center justify-between gap-4">
	<span>{label}</span>
	<button
		role="switch"
		aria-checked={checked}
		aria-label={label}
		onclick={() => {
			checked = !checked;
			onchange(checked);
		}}
		class="relative h-6 w-10 shrink-0 rounded-full {checked ? 'bg-accent' : 'bg-line'}"
	>
		<span class="absolute top-0.5 left-0.5 h-5 w-5 rounded-full bg-bg transition-transform {checked ? 'translate-x-4' : ''}"></span>
	</button>
</label>
