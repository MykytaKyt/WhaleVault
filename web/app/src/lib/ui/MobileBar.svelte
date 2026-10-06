<script>
	import { Menu, Search } from '@lucide/svelte';
	import { nav, openPalette } from '#lib/state.svelte.js';
</script>

<!-- Phone only: hamburger, app name, search -->
<header class="sticky top-0 z-20 flex h-14 items-center gap-1 border-b border-line bg-bg px-2 md:hidden">
	<button class="icon-btn" aria-label="Меню" onclick={() => (nav.open = true)}><Menu size={20} /></button>
	<a href="/" class="flex items-center gap-1.5 px-1 font-semibold"><span aria-hidden="true">🐋</span>WhaleVault</a>
	<button class="icon-btn ml-auto" aria-label="Поиск" onclick={() => openPalette()}><Search size={20} /></button>
</header>
