<script lang="ts">
	import { page } from '$app/stores';
	import { api } from '$lib/api';
	import { goto } from '$app/navigation';

	const code = $page.params.code;
	let password = $state('');
	let confirmPassword = $state('');
	let loading = $state(false);
	let error = $state<string | null>(null);

	async function handleSubmit(e: SubmitEvent) {
		e.preventDefault();
		if (!password || !confirmPassword) {
			error = 'Please fill in all fields.';
			return;
		}

		if (password !== confirmPassword) {
			error = 'Passwords do not match.';
			return;
		}

		if (password.length < 6) {
			error = 'Password must be at least 6 characters long.';
			return;
		}

		loading = true;
		error = null;

		try {
			await api.redeemInvite(code, password);
			goto('/');
		} catch (err: any) {
			error = err.message || 'Failed to redeem invite.';
		} finally {
			loading = false;
		}
	}
</script>

<div class="bg-slate-900/60 backdrop-blur-xl border border-slate-800/80 p-8 rounded-3xl shadow-2xl relative">
	<div class="absolute -top-12 left-1/2 -translate-x-1/2 p-4 rounded-2xl bg-gradient-to-tr from-indigo-500 to-purple-500 text-white shadow-xl shadow-indigo-500/20">
		<svg class="w-8 h-8" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M18 9v3m0 0v3m0-3h3m-3 0h-3m-2-5a4 4 0 11-8 0 4 4 0 018 0zM3 20a6 6 0 0112 0v1H3v-1z"/></svg>
	</div>

	<div class="text-center mt-6 mb-8">
		<h2 class="text-2xl font-extrabold text-white tracking-tight">Redeem Invite</h2>
		<p class="text-xs text-slate-400 mt-2">Code: <span class="text-indigo-400 font-mono font-semibold">{code}</span></p>
	</div>

	{#if error}
		<div class="mb-6 px-4 py-3 rounded-xl bg-red-500/10 border border-red-500/20 text-red-400 text-xs font-medium flex items-center gap-2">
			<svg class="w-4 h-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"/></svg>
			{error}
		</div>
	{/if}

	<form onsubmit={handleSubmit} class="flex flex-col gap-5">
		<div class="flex flex-col gap-2">
			<label for="password" class="text-xs font-semibold text-slate-300">Set Password</label>
			<input 
				type="password" 
				id="password" 
				bind:value={password}
				placeholder="At least 6 characters"
				class="px-4 py-3 rounded-xl bg-slate-950/50 border border-slate-800 text-sm text-white placeholder-slate-600 focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 transition-all duration-200"
				required
			/>
		</div>

		<div class="flex flex-col gap-2">
			<label for="confirm-password" class="text-xs font-semibold text-slate-300">Confirm Password</label>
			<input 
				type="password" 
				id="confirm-password" 
				bind:value={confirmPassword}
				placeholder="Confirm password"
				class="px-4 py-3 rounded-xl bg-slate-950/50 border border-slate-800 text-sm text-white placeholder-slate-600 focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 transition-all duration-200"
				required
			/>
		</div>

		<button 
			type="submit" 
			disabled={loading}
			id="redeem-submit-btn"
			class="w-full mt-2 py-3 rounded-xl bg-indigo-600 hover:bg-indigo-500 disabled:bg-indigo-600/50 text-white font-semibold text-sm shadow-lg shadow-indigo-600/10 hover:shadow-indigo-600/20 active:scale-[0.98] transition-all duration-200 flex items-center justify-center gap-2"
		>
			{#if loading}
				<div class="w-4 h-4 rounded-full border-2 border-white/30 border-t-white animate-spin"></div>
				Redeeming...
			{:else}
				Activate Account & Sign In
			{/if}
		</button>
	</form>
</div>
