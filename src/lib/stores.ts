import { writable } from 'svelte/store';
import type { VerticalLayout } from './types';
import { erpclaw } from './mock/erpclaw';

// Keep local fixtures for navigation and form metadata only. Business values
// must always come from the ERP database API.
function viewMetadata(layout: VerticalLayout): VerticalLayout {
	return { ...layout, kpis: [], workflows: [], mockData: {}, attention: [], activity: [] };
}

export const layout = writable<VerticalLayout>(viewMetadata(erpclaw));

export async function loadLayout(): Promise<void> {
	try {
		const response = await fetch('/api/layout/erpclaw');
		if (!response.ok) return;

		const loaded: VerticalLayout = await response.json();
		if (loaded.name === 'erpclaw') layout.set(viewMetadata(loaded));
	} catch {
		// Keep the local navigation when the API is unavailable.
	}
}
