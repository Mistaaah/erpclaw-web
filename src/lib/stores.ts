import { writable, derived } from 'svelte/store';
import type { VerticalLayout } from './types';
import { erpclaw } from './mock/erpclaw';
import { dental } from './mock/dental';
import { property } from './mock/property';

// Keep local fixtures for navigation and form metadata only. Business values
// must always come from the ERP database API.
function viewMetadata(layout: VerticalLayout): VerticalLayout {
	return { ...layout, kpis: [], workflows: [], mockData: {}, attention: [], activity: [] };
}

const mockVerticals: Record<string, VerticalLayout> = {
	erpclaw: viewMetadata(erpclaw),
	dental: viewMetadata(dental),
	property: viewMetadata(property)
};

// Live verticals store — starts with mock, updated by API
export const verticals = writable<Record<string, VerticalLayout>>(mockVerticals);

export const currentVerticalKey = writable<string>('erpclaw');

export const layout = derived(
	[currentVerticalKey, verticals],
	([$key, $verticals]) => $verticals[$key] ?? mockVerticals.erpclaw
);

/** Fetch verticals list from API, then load each layout */
export async function loadVerticals(): Promise<void> {
	try {
		const res = await fetch('/api/layout/verticals');
		if (!res.ok) return; // Fall back to mock

		const data = await res.json();
		const names: string[] = (data.verticals ?? []).map((v: { name: string }) => v.name);

		// Fetch each vertical's full layout in parallel
		const layouts = await Promise.all(
			names.map(async (name) => {
				const r = await fetch(`/api/layout/${name}`);
				if (!r.ok) return null;
				return r.json() as Promise<VerticalLayout>;
			})
		);

		const loaded: Record<string, VerticalLayout> = {};
		for (const l of layouts) {
			if (l && l.name) loaded[l.name] = viewMetadata(l);
		}

		if (Object.keys(loaded).length > 0) {
			verticals.set(loaded);
		}
	} catch {
		// API unavailable — mock data stays in place
	}
}
