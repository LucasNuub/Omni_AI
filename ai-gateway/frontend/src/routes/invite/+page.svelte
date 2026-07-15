<script lang="ts">
	import { goto } from '$app/navigation';
</script>

<div class="bg-slate-900/60 backdrop-blur-xl border border-slate-800/80 p-8 rounded-3xl shadow-2xl text-center flex flex-col items-center gap-4">
	<div class="p-3 rounded-2xl bg-amber-500/10 text-amber-400 border border-amber-500/20">
		<svg class="w-8 h-8" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"/></svg>
	</div>
	<h2 class="text-xl font-bold text-white mt-2">Missing Invite Code</h2>
	<p class="text-xs text-slate-400 max-w-xs leading-relaxed">Registration requires a full invite URL (e.g., /invite/CODE). Please check the link provided by your administrator.</p>
	<button
		onclick={() => goto('/login')}
		class="w-full mt-4 py-2.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-white text-xs font-semibold transition-all duration-200"
	>
		Go to Login
	</button>
</div>
