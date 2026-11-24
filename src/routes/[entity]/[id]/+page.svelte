<script lang="ts">
	import EntityDetail from '$lib/components/EntityDetail.svelte';
	import { layout } from '$lib/stores';
	import { page } from '$app/stores';
	import { fetchEntityRecord } from '$lib/api';
	import { isLoading as authLoading, isAuthenticated } from '$lib/auth';

	let entityKey = $derived($page.params.entity ?? '');
	let id = $derived($page.params.id ?? '0');
	let entityDef = $derived(entityKey ? $layout.entities[entityKey] : undefined);
	let record = $state<Record<string, unknown> | null>(null);
	let loading = $state(true);
	let notFound = $state(false);
	let failed = $state(false);
	let requestId = 0;
	$effect(() => {
		if (!$authLoading && $isAuthenticated && entityKey && id) loadRecord(entityKey, id);
	});
	async function loadRecord(key: string, recordId: string) {
		const request = ++requestId;
		loading = true;
		record = null;
		notFound = false;
		failed = false;
		const result = await fetchEntityRecord(key, recordId);
		if (request !== requestId) return;
		if (!result) failed = true;
		else if (result.notFound) notFound = true;
		else record = result.row;
		loading = false;
	}
</script>

{#if loading}
	<p class="py-12 text-center text-sm text-muted">Loading record…</p>
{:else if entityDef && record}
	<div class="mx-auto max-w-4xl">
		<EntityDetail
			record={record}
			entityDef={entityDef}
			panel={false}
		/>
	</div>
{:else if notFound || (!loading && !failed)}
	<div class="flex flex-col items-center justify-center py-20 text-center">
		<p class="text-4xl">📭</p>
		<p class="mt-3 text-lg font-medium">Record not found</p>
		<p class="mt-1 text-sm text-muted">Could not find this {entityKey} record.</p>
		<a href="/{entityKey}" class="mt-4 text-sm text-accent hover:underline">← Back to list</a>
	</div>
{:else if failed}
	<div class="flex flex-col items-center justify-center py-20 text-center">
		<p class="mt-3 text-lg font-medium">Could not load record</p>
		<p class="mt-1 text-sm text-muted">The ERP database request failed. Refresh to try again.</p>
		<a href="/{entityKey}" class="mt-4 text-sm text-accent hover:underline">← Back to list</a>
	</div>
{/if}
