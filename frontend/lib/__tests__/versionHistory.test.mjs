/**
 * Subtask 3 — version history data helpers.
 *
 * Pure Node tests: the modal only has to render what these helpers return.
 */
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { formatDateTime, formatFileSize } from "../formatters.ts";
import { normalizeVersionHistory } from "../versionHistory.ts";

describe("normalizeVersionHistory", () => {
	it("reads the backend envelope and sorts oldest first", () => {
		const entries = normalizeVersionHistory({
			document_id: 1,
			version: 2,
			versions: [
				{ id: 2, version: 2, status: "Indexed", is_current: true },
				{ id: 1, version: 1, status: "Archived", is_current: false },
			],
		});

		assert.deepEqual(
			entries.map((entry) => entry.version),
			[1, 2],
		);
		assert.equal(entries[0].status, "Archived");
		assert.equal(entries[1].is_current, true);
	});

	it("also accepts a bare array and drops malformed rows", () => {
		const entries = normalizeVersionHistory([
			null,
			{ id: "x", version: 1 },
			{ id: 9, version: 0 },
			{ id: 3, version: 3 },
			{ id: 1, version: 1 },
		]);

		assert.deepEqual(
			entries.map((entry) => entry.id),
			[1, 3],
		);
	});

	it("returns an empty list for missing or broken payloads", () => {
		assert.deepEqual(normalizeVersionHistory(undefined), []);
		assert.deepEqual(normalizeVersionHistory({ versions: "nope" }), []);
	});
});

describe("formatters", () => {
	it("formats sizes consistently", () => {
		assert.equal(formatFileSize(undefined), "—");
		assert.equal(formatFileSize(512), "512 B");
		assert.equal(formatFileSize(2048), "2.0 KB");
		assert.equal(formatFileSize(2 * 1024 * 1024), "2.0 MB");
	});

	it("formats UTC timestamps deterministically", () => {
		const value = "2026-11-16T09:00:00Z";
		const formatted = formatDateTime(value, "en");

		assert.match(formatted, /2026/);
		assert.match(formatted, /Nov/);
		assert.equal(formatDateTime("not-a-date"), "—");
		assert.equal(formatDateTime(null), "—");
		assert.doesNotThrow(() => formatDateTime(value, "fa"));
	});
});
