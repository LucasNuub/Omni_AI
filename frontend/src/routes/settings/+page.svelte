<script lang="ts">
	import { api, type ProviderKey } from '$lib/api';
	import { onMount } from 'svelte';

	let keys = $state<ProviderKey[]>([]);
	let loading = $state(true);

	// Wizard Form State
	let selectedProvider = $state('groq');
	let apiKey = $state('');
	let nickname = $state('');
	let submitting = $state(false);

	// Key Discovery Stepper State
	let pollingKeyId = $state<string | null>(null);
	let discoveryStep = $state<'verifying_key' | 'discovering_models' | 'benchmarking' | 'done' | 'failed' | null>(null);
	let discoveryError = $state<string | null>(null);
	let modelsAddedCount = $state(0);

	// List of MVP providers
	const providersInfo = [
		{ id: 'groq', name: 'Groq', needsKey: true },
		{ id: 'gemini', name: 'Google Gemini API', needsKey: true },
		{ id: 'openrouter', name: 'OpenRouter', needsKey: true },
		{ id: 'pollinations', name: 'Pollinations', needsKey: false },
		{ id: 'huggingface', name: 'HuggingFace Inference', needsKey: true },
		{ id: 'deepseek', name: 'DeepSeek Platform', needsKey: true },
		{ id: 'ollama', name: 'Ollama (local)', needsKey: false }
	];

	let currentProviderNeedsKey = $derived.by(() => {
		const info = providersInfo.find(p => p.id === selectedProvider);
		return info ? info.needsKey : true;
	});

	async function fetchKeys() {
		try {
			keys = await api.getKeys();
		} catch (err) {
			console.error(err);
		} finally {
			loading = false;
		}
	}

	onMount(() => {
		fetchKeys();
	});

	async function handleAddKey(e: Event) {
		e.preventDefault();
		if (currentProviderNeedsKey && !apiKey) return;

		submitting = true;
		discoveryStep = 'verifying_key';
		discoveryError = null;
		modelsAddedCount = 0;

		try {
			// Step 1: Add/Save pending key
			const result = await api.addKey(selectedProvider, apiKey, nickname);
			pollingKeyId = result.id;
			
			// Refresh key list immediately (will show as pending)
			await fetchKeys();

			// Step 2: Start polling key verification progress
			startPolling(result.id);
		} catch (err: any) {
			discoveryStep = 'failed';
			discoveryError = err.message || 'Failed to initialize key onboarding.';
			submitting = false;
		}
	}

	function startPolling(id: string) {
		const interval = setInterval(async () => {
			try {
				const res = await api.getKeyDiscoveryStatus(id);
				discoveryStep = res.step;
				modelsAddedCount = res.models_added;

				if (res.status === 'active' || res.step === 'done') {
					clearInterval(interval);
					submitting = false;
					pollingKeyId = null;
					apiKey = '';
					nickname = '';
					await fetchKeys(); // Refresh key list to show active status
				} else if (res.step === 'failed') {
					clearInterval(interval);
					submitting = false;
					discoveryError = res.error || 'Discovery verification failed.';
					await fetchKeys(); // Refresh key list to show failure status
				}
			} catch (err: any) {
				clearInterval(interval);
				submitting = false;
				discoveryStep = 'failed';
				discoveryError = err.message || 'Error occurred during status polling.';
			}
		}, 1500);
	}

	async function handleRescan(id: string) {
		try {
			await api.rescanKey(id);
			discoveryStep = 'verifying_key';
			submitting = true;
			startPolling(id);
		} catch (err) {
			console.error(err);
		}
	}

	async function handleDelete(id: string) {
		if (confirm('Are you sure you want to delete this credentials key? This action is irreversible.')) {
			try {
				await api.deleteKey(id);
				await fetchKeys();
			} catch (err) {
				console.error(err);
			}
		}
	}
</script>

<div class="flex-1 flex flex-col gap-8">
	<!-- Page Header -->
	<div>
		<h2 class="text-xl font-bold text-white tracking-tight">Onboarding & Credentials Settings</h2>
		<p class="text-xs text-slate-400 mt-0.5">Add provider keys, trigger background scans, and manage access tokens</p>
	</div>

	<!-- Add Provider Wizard -->
	<div class="bg-slate-900/40 border border-slate-800/80 rounded-2xl p-6 flex flex-col gap-6 relative overflow-hidden">
		<h3 class="text-sm font-extrabold text-white tracking-tight flex items-center gap-2">
			<span class="p-1 rounded-lg bg-indigo-500/10 text-indigo-400">
				<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v3m0 0v3m0-3h3m-3 0h-3m-2-5a4 4 0 11-8 0 4 4 0 018 0zM3 20a6 6 0 0112 0v1H3v-1z"/></svg>
			</span>
			Add Provider Credentials
		</h3>

		<form onsubmit={handleAddKey} class="grid grid-cols-1 md:grid-cols-3 gap-5 items-end">
			<!-- Select Provider -->
			<div class="flex flex-col gap-2">
				<label for="provider-select" class="text-xs font-semibold text-slate-300">AI Provider</label>
				<select
					id="provider-select"
					bind:value={selectedProvider}
					disabled={submitting}
					class="px-4 py-3 rounded-xl bg-slate-950/50 border border-slate-800 text-sm text-slate-300 focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 transition-all duration-200"
				>
					{#each providersInfo as p}
						<option value={p.id}>{p.name}</option>
					{/each}
				</select>
			</div>

			<!-- API Key (Conditional) -->
			<div class="flex flex-col gap-2 {currentProviderNeedsKey ? '' : 'opacity-40 pointer-events-none'}">
				<label for="api-key" class="text-xs font-semibold text-slate-300">API Key</label>
				<input
					type="password"
					id="api-key"
					bind:value={apiKey}
					placeholder={currentProviderNeedsKey ? "Paste your API key here..." : "No credentials needed"}
					disabled={submitting || !currentProviderNeedsKey}
					required={currentProviderNeedsKey}
					class="px-4 py-3 rounded-xl bg-slate-950/50 border border-slate-800 text-sm text-white placeholder-slate-600 focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 transition-all duration-200"
				/>
			</div>

			<!-- Nickname & Add Button -->
			<div class="flex gap-3">
				<div class="flex-1 flex flex-col gap-2">
					<label for="nickname" class="text-xs font-semibold text-slate-300">Nickname (Optional)</label>
					<input
						type="text"
						id="nickname"
						bind:value={nickname}
						placeholder="e.g. My Shared Key"
						disabled={submitting}
						class="w-full px-4 py-3 rounded-xl bg-slate-950/50 border border-slate-800 text-sm text-white placeholder-slate-600 focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 transition-all duration-200"
					/>
				</div>

				<button
					type="submit"
					disabled={submitting || (currentProviderNeedsKey && !apiKey)}
					id="settings-add-provider-btn"
					class="px-6 py-3 rounded-xl bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-800 text-white disabled:text-slate-500 font-semibold text-sm shadow-lg shadow-indigo-600/10 hover:shadow-indigo-600/20 active:scale-[0.98] transition-all duration-200 shrink-0"
				>
					Add Provider
				</button>
			</div>
		</form>

		<!-- Live Stepper Checklist -->
		{#if discoveryStep}
			<div class="mt-4 p-5 rounded-xl border bg-slate-950/20 border-slate-800/80">
				<h4 class="text-xs font-bold text-slate-400 uppercase tracking-wider mb-4">Discovery Pipeline Status:</h4>
				<div class="flex flex-col gap-3">
					<!-- Step 1: Verification -->
					<div class="flex items-center gap-3">
						<div class="w-5 h-5 rounded-full flex items-center justify-center text-xs border {discoveryStep === 'verifying_key' ? 'border-indigo-500 bg-indigo-500/10 text-indigo-400' : (discoveryStep === 'failed' ? 'border-red-500 bg-red-500/10 text-red-400' : 'border-slate-800 bg-slate-900 text-slate-600')}">
							{#if discoveryStep === 'verifying_key'}
								<div class="w-2.5 h-2.5 rounded-full border border-indigo-400 border-t-transparent animate-spin"></div>
							{:else if discoveryStep === 'failed'}
								✕
							{:else}
								✓
							{/if}
						</div>
						<span class="text-xs font-medium {discoveryStep === 'verifying_key' ? 'text-indigo-400' : (discoveryStep === 'failed' ? 'text-red-400' : 'text-slate-400')}">Verifying key credentials...</span>
					</div>

					<!-- Step 2: Discovering Models -->
					<div class="flex items-center gap-3">
						<div class="w-5 h-5 rounded-full flex items-center justify-center text-xs border {discoveryStep === 'discovering_models' ? 'border-indigo-500 bg-indigo-500/10 text-indigo-400' : (discoveryStep === 'verifying_key' ? 'border-slate-800 text-slate-600' : 'border-slate-800 bg-slate-900 text-slate-400')}">
							{#if discoveryStep === 'discovering_models'}
								<div class="w-2.5 h-2.5 rounded-full border border-indigo-400 border-t-transparent animate-spin"></div>
							{:else if ['verifying_key', 'failed'].includes(discoveryStep)}
								○
							{:else}
								✓
							{/if}
						</div>
						<span class="text-xs font-medium {discoveryStep === 'discovering_models' ? 'text-indigo-400' : (['verifying_key', 'failed'].includes(discoveryStep) ? 'text-slate-600' : 'text-slate-400')}">Discovering live models...</span>
					</div>

					<!-- Step 3: Benchmarking -->
					<div class="flex items-center gap-3">
						<div class="w-5 h-5 rounded-full flex items-center justify-center text-xs border {discoveryStep === 'benchmarking' ? 'border-indigo-500 bg-indigo-500/10 text-indigo-400' : (['verifying_key', 'discovering_models', 'failed'].includes(discoveryStep) ? 'border-slate-800 text-slate-600' : 'border-slate-800 bg-slate-900 text-slate-400')}">
							{#if discoveryStep === 'benchmarking'}
								<div class="w-2.5 h-2.5 rounded-full border border-indigo-400 border-t-transparent animate-spin"></div>
							{:else if ['verifying_key', 'discovering_models', 'failed'].includes(discoveryStep)}
								○
							{:else}
								✓
							{/if}
						</div>
						<span class="text-xs font-medium {discoveryStep === 'benchmarking' ? 'text-indigo-400' : (['verifying_key', 'discovering_models', 'failed'].includes(discoveryStep) ? 'text-slate-600' : 'text-slate-400')}">Benchmarking latencies...</span>
					</div>

					<!-- Step 4: Done -->
					{#if discoveryStep === 'done'}
						<div class="mt-2 text-emerald-400 text-xs font-semibold flex items-center gap-1.5">
							<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7"/></svg>
							Done — Onboarding complete! {modelsAddedCount} models successfully added.
						</div>
					{/if}

					<!-- Fail Error block -->
					{#if discoveryError}
						<div class="mt-2 text-red-400 text-xs font-medium bg-red-500/5 p-3 rounded-lg border border-red-500/10">
							<strong>Error:</strong> {discoveryError}
						</div>
					{/if}
				</div>
			</div>
		{/if}
	</div>

	<!-- Existing Keys list -->
	<div class="bg-slate-900/40 border border-slate-800/80 rounded-2xl overflow-hidden flex flex-col">
		<div class="p-6 border-b border-slate-800/60 flex justify-between items-center bg-slate-950/20">
			<h3 class="text-sm font-extrabold text-white tracking-tight flex items-center gap-2">
				<span class="p-1 rounded-lg bg-indigo-500/10 text-indigo-400">
					<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 7a2 2 0 012 2m0-2a2 2 0 01-2-2m2 2a2 2 0 002 2m0 0a2 2 0 01-2 2m2-2h.01M9 12a3 3 0 11-6 0 3 3 0 016 0zM12 17H3m9 0a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1"/></svg>
				</span>
				Registered Provider Credentials
			</h3>
			<span class="text-xs text-slate-500 font-semibold bg-slate-900 border border-slate-800 px-3 py-1.5 rounded-xl">
				Stored keys: {keys.length}
			</span>
		</div>

		<div class="overflow-x-auto">
			<table class="w-full text-left border-collapse">
				<thead>
					<tr class="bg-slate-950/20 border-b border-slate-800/60 text-slate-400 text-[10px] font-bold uppercase tracking-wider">
						<th class="py-4 px-6">Nickname / Provider</th>
						<th class="py-4 px-4">Masked Key</th>
						<th class="py-4 px-4">Daily Usage (Today)</th>
						<th class="py-4 px-4">Key Status</th>
						<th class="py-4 px-4">Onboarded</th>
						<th class="py-4 px-6 text-right">Actions</th>
					</tr>
				</thead>
				<tbody class="divide-y divide-slate-800/60 text-xs">
					{#if loading && keys.length === 0}
						<tr>
							<td colspan="6" class="py-12 text-center text-slate-500 font-medium">
								Loading stored keys...
							</td>
						</tr>
					{:else if keys.length === 0}
						<tr>
							<td colspan="6" class="py-12 text-center text-slate-500 font-medium">
								No keys registered. Add credentials above to begin.
							</td>
						</tr>
					{/if}
					{#each keys as key}
						<tr class="hover:bg-slate-800/10 transition-colors">
							<!-- Nickname & Provider -->
							<td class="py-4 px-6">
								<div class="flex flex-col">
									<div class="flex items-center gap-2">
										<!-- Health dot -->
										<span class="h-2 w-2 rounded-full {key.health_status === 'green' ? 'bg-emerald-500' : key.health_status === 'yellow' ? 'bg-amber-500' : 'bg-red-500'}"></span>
										<span class="font-bold text-white text-sm">{key.nickname}</span>
									</div>
									<span class="text-[10px] text-slate-500 font-semibold uppercase tracking-wider mt-0.5 ml-4">
										{key.provider_name}
									</span>
								</div>
							</td>
							<!-- Masked Key -->
							<td class="py-4 px-4 font-mono text-slate-400">
								{key.encrypted_key}
							</td>
							<!-- Usage -->
							<td class="py-4 px-4 font-mono text-slate-200">
								{key.daily_usage_count.toLocaleString()} / {key.daily_limit ? key.daily_limit.toLocaleString() : 'unlimited'}
							</td>
							<!-- Key Onboarding Status -->
							<td class="py-4 px-4">
								<span class="px-2 py-0.5 text-[9px] font-bold rounded capitalize {key.status === 'active' ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' : key.status === 'pending' ? 'bg-indigo-500/10 text-indigo-400 border border-indigo-500/20' : 'bg-red-500/10 text-red-400 border border-red-500/20'}">
									{key.status}
								</span>
							</td>
							<!-- Added at date -->
							<td class="py-4 px-4 text-slate-500">
								{new Date(key.added_at).toLocaleDateString()}
							</td>
							<!-- Actions -->
							<td class="py-4 px-6 text-right space-x-2">
								<button
									onclick={() => handleRescan(key.id)}
									disabled={submitting}
									class="px-3 py-1.5 rounded-lg border border-slate-800 hover:border-indigo-500/30 text-[10px] font-semibold text-slate-400 hover:text-indigo-400 hover:bg-indigo-500/5 transition-all duration-200"
								>
									Rescan
								</button>
								<button
									onclick={() => handleDelete(key.id)}
									disabled={submitting}
									class="px-3 py-1.5 rounded-lg border border-slate-800 hover:border-red-500/30 text-[10px] font-semibold text-slate-400 hover:text-red-400 hover:bg-red-500/5 transition-all duration-200"
								>
									Delete
								</button>
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	</div>
</div>
