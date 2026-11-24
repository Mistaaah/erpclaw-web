import { describe, it, expect } from 'vitest';
import { get } from 'svelte/store';
import { layout } from '$lib/stores';

describe('stores', () => {
	it('defaults to the ERPClaw workspace without sample records', () => {
		const active = get(layout);
		expect(active.name).toBe('erpclaw');
		expect(active.label).toBe('ERPClaw');
		expect(active.mockData).toEqual({});
	});
});
