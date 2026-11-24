<script lang="ts">
	import KPIGrid from '$lib/components/KPIGrid.svelte';
	import WorkflowPipeline from '$lib/components/WorkflowPipeline.svelte';
	import AttentionList from '$lib/components/AttentionList.svelte';
	import ActivityFeed from '$lib/components/ActivityFeed.svelte';
	import { onMount } from 'svelte';
	import { fetchDashboardOverview, type DashboardOverview } from '$lib/api';
	import { currentVerticalKey } from '$lib/stores';

	let overview = $state<DashboardOverview | null>(null);
	let loading = $state(true);
	onMount(async () => {
		overview = await fetchDashboardOverview();
		loading = false;
	});
</script>

<div class="mx-auto max-w-6xl space-y-6">
	<div>
		<h1 class="text-lg font-semibold">Dashboard</h1>
		<p class="text-sm text-muted">Live business overview</p>
	</div>

	{#if $currentVerticalKey !== 'erpclaw'}
		<div class="rounded-xl border border-border p-6 text-sm text-muted" role="status">
			Live dashboard metrics are not available for this workspace yet.
		</div>
	{:else if loading}
		<p class="rounded-xl border border-border p-6 text-sm text-muted">Loading business data…</p>
	{:else if !overview}
		<div class="rounded-xl border border-border p-6 text-sm text-muted" role="status">
			Dashboard data is unavailable. Check the ERP database connection and refresh this page.
		</div>
	{:else}
		<KPIGrid items={overview.kpis} />

		{#if overview.workflows.length}
			<div class="space-y-3">
				<h2 class="text-sm font-medium text-muted">Workflows</h2>
				{#each overview.workflows as wf, i}
					<WorkflowPipeline workflow={wf} index={i} />
				{/each}
			</div>
		{/if}

		<div class="grid gap-6 lg:grid-cols-2">
			<AttentionList items={overview.attention} />
			<ActivityFeed items={overview.activity} />
		</div>
	{/if}
</div>
