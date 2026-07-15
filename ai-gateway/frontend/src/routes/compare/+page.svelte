<script lang="ts">
	import { api, type Model } from '$lib/api';
	import { onMount } from 'svelte';

	let models = $state<Model[]>([]);
	let selectedModelIds = $state<string[]>([]);
	let promptText = $state('');
	let loading = $state(false);
	
	// Hold the comparative outcomes
	let columns = $state<Array<{ modelId: string; modelName: string; providerName: string; content: string }>>([]);

	onMount(async () => {
		try {
			models = await api.getModels();
			if (models.length > 0) {
				// Select first two models by default
				const active = models.filter(m => m.enabled);
				selectedModelIds = active.slice(0, 2).map(m => m.model_id);
			}
		} catch (err) {
			console.error(err);
		}
	});

	function handleModelToggle(modelId: string) {
		if (selectedModelIds.includes(modelId)) {
			selectedModelIds = selectedModelIds.filter(id => id !== modelId);
		} else {
			if (selectedModelIds.length >= 3) {
				// Capped at 3 models side-by-side
				return;
			}
			selectedModelIds = [...selectedModelIds, modelId];
		}
	}

	async function runComparison(e: Event) {
		e.preventDefault();
		if (!promptText.trim() || selectedModelIds.length === 0) return;

		loading = true;
		
		// Initialize columns
		columns = selectedModelIds.map(modelId => {
			const m = models.find(x => x.model_id === modelId);
			return {
				modelId,
				modelName: m ? m.display_name : modelId,
				providerName: m ? m.provider_name.toUpperCase() : 'UNKNOWN',
				content: ''
			};
		});

		// Start streaming completions in parallel
		const promises = columns.map(async (col, idx) => {
			try {
				await api.chatCompletion(
					[{ role: 'user', content: promptText.trim() }],
					col.modelId,
					'balanced',
					(chunk) => {
						columns[idx].content += chunk;
						columns = [...columns]; // Reactivity trigger
					}
				);
			} catch (err) {
				columns[idx].content = '⚠️ Error routing to provider adapter.';
				columns = [...columns];
			}
		});

		await Promise.all(promises);
		loading = false;
	}
</script>

<div class="flex-1 flex flex-col gap-6">
	<!-- Page Header -->
	<div>
		<h2 class="text-xl font-bold text-white tracking-tight">Provider Model Comparison</h2>
		<p class="text-xs text-slate-400 mt-0.5">Test multiple models simultaneously and compare responses side-by-side</p>
	</div>

	<!-- Configuration panel -->
	<div class="bg-slate-900/40 border border-slate-800/80 p-6 rounded-2xl flex flex-col gap-5">
		<!-- Model picker checkboxes -->
		<div>
			<h3 class="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">Select 2-3 Models:</h3>
			<div class="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-3">
				{#each models.filter(m => m.enabled) as model}
					{@const isChecked = selectedModelIds.includes(model.model_id)}
					<button
						onclick={() => handleModelToggle(model.model_id)}
						disabled={loading}
						class="flex items-center justify-between p-3 rounded-xl border text-left transition-all duration-200 {isChecked ? 'bg-indigo-500/10 border-indigo-500 text-white' : 'bg-slate-950/20 border-slate-800/60 text-slate-400 hover:border-slate-700/60'}"
					>
						<div class="flex flex-col min-w-0">
							<span class="text-xs font-bold truncate">{model.display_name}</span>
							<span class="text-[10px] opacity-60 mt-0.5">{model.provider_name.toUpperCase()}</span>
						</div>
						<div class="w-4 h-4 rounded-md border flex items-center justify-center {isChecked ? 'border-indigo-500 bg-indigo-600 text-white' : 'border-slate-800 bg-transparent'}">
							{#if isChecked}
								<svg class="w-3 h-3" fill="none" stroke="currentColor" stroke-width="3" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7"/></svg>
							{/if}
						</div>
					</button>
				{/each}
			</div>
		</div>

		<!-- Prompt Input -->
		<form onsubmit={runComparison} class="flex flex-col gap-4">
			<div class="flex flex-col gap-2">
				<label for="prompt" class="text-xs font-semibold text-slate-300">Prompt Text:</label>
				<textarea
					id="prompt"
					bind:value={promptText}
					disabled={loading}
					placeholder="Enter a prompt to compare, e.g. 'Write a python quicksort function...'"
					rows="3"
					class="px-4 py-3 rounded-xl bg-slate-950/40 border border-slate-800 text-sm text-white placeholder-slate-600 focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 transition-all duration-200"
					required
				></textarea>
			</div>

			<button
				type="submit"
				disabled={loading || !promptText.trim() || selectedModelIds.length < 2}
				id="compare-submit-btn"
				class="w-fit self-end px-6 py-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-800 text-white disabled:text-slate-500 font-semibold text-sm shadow-lg shadow-indigo-600/10 transition-all duration-200 flex items-center gap-2"
			>
				{#if loading}
					<div class="w-4 h-4 rounded-full border-2 border-white/30 border-t-white animate-spin"></div>
					Evaluating Responses...
				{:else}
					Run Comparison
				{/if}
			</button>
		</form>
	</div>

	<!-- Results Columns -->
	{#if columns.length > 0}
		<div class="grid grid-cols-1 md:grid-cols-{columns.length} gap-4 flex-1">
			{#each columns as col}
				<div class="bg-slate-900/40 border border-slate-800/80 rounded-2xl overflow-hidden flex flex-col h-[50vh]">
					<!-- Header -->
					<div class="bg-slate-950/40 border-b border-slate-800/60 p-4 shrink-0 flex items-center justify-between">
						<div class="min-w-0">
							<h4 class="font-bold text-xs text-white truncate">{col.modelName}</h4>
							<p class="text-[10px] text-slate-500 font-semibold uppercase mt-0.5">{col.providerName}</p>
						</div>
						<span class="px-2 py-0.5 text-[9px] font-bold rounded bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
							Active
						</span>
					</div>
					<!-- Content -->
					<div class="p-5 overflow-y-auto flex-1 text-sm text-slate-200 leading-relaxed whitespace-pre-wrap font-sans selection:bg-indigo-500/20">
						{#if col.content === ''}
							<div class="h-full flex items-center justify-center">
								<div class="flex gap-1.5">
									<span class="w-2 h-2 rounded-full bg-indigo-500 animate-bounce" style="animation-delay: 0ms"></span>
									<span class="w-2 h-2 rounded-full bg-indigo-500 animate-bounce" style="animation-delay: 150ms"></span>
									<span class="w-2 h-2 rounded-full bg-indigo-500 animate-bounce" style="animation-delay: 300ms"></span>
								</div>
							</div>
						{:else}
							{col.content}
						{/if}
					</div>
				</div>
			{/each}
		</div>
	{/if}
</div>
