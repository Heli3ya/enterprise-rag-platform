/**
 * Subtask 1 — upload format guidance.
 *
 * The chips in the drop zone, the `accept` attribute and the client gate all
 * come from `uploadFormats.ts`. These tests pin that contract so the new
 * Excel/Email/Image guidance can never again drift from what the API accepts.
 */
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
	ALLOWED_EXTENSIONS,
	ALLOWED_MIME_TYPES,
	isAllowedUploadFile,
	UPLOAD_ACCEPT,
	UPLOAD_FORMAT_GROUPS,
} from "../uploadFormats.ts";

describe("upload format catalogue", () => {
	it("exposes every backend-supported family exactly once", () => {
		assert.deepEqual(
			UPLOAD_FORMAT_GROUPS.map((group) => group.key),
			["pdf", "word", "text", "excel", "email", "image"],
		);

		const labels = UPLOAD_FORMAT_GROUPS.map((group) => group.label);

		assert.deepEqual(labels, [
			"PDF",
			"Word",
			"TXT",
			"Excel / CSV",
			"Email",
			"Images",
		]);
		assert.ok(UPLOAD_FORMAT_GROUPS.every((group) => group.icon.length > 0));
	});

	it("derives the accept string from the same groups as the icons", () => {
		assert.equal(
			UPLOAD_ACCEPT,
			".pdf,.doc,.docx,.txt,.xlsx,.csv,.eml,.jpg,.jpeg,.png",
		);

		for (const group of UPLOAD_FORMAT_GROUPS) {
			for (const extension of group.extensions) {
				assert.ok(ALLOWED_EXTENSIONS.includes(extension));
			}
			for (const mime of group.mimeTypes) {
				assert.ok(ALLOWED_MIME_TYPES.includes(mime));
			}
		}
	});
});

describe("client-side file gate", () => {
	const cases = [
		["policy.pdf", "application/pdf"],
		[
			"report.docx",
			"application/vnd.openxmlformats-officedocument.wordprocessingml.document",
		],
		["notes.txt", "text/plain"],
		[
			"prices.xlsx",
			"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
		],
		["prices.csv", "text/csv"],
		["prices.csv", "application/vnd.ms-excel"],
		["invoice.eml", "message/rfc822"],
		["scan.png", "image/png"],
		["scan.jpg", "image/jpeg"],
		["unknown.txt", "application/octet-stream"],
	];

	for (const [name, mime] of cases) {
		it(`accepts ${name} (${mime})`, () => {
			assert.equal(isAllowedUploadFile(name, mime), true);
		});
	}

	it("accepts an empty MIME type because browsers guess it from the extension", () => {
		assert.equal(isAllowedUploadFile("scan.PNG", ""), true);
	});

	it("rejects formats the server cannot ingest", () => {
		assert.equal(isAllowedUploadFile("animation.gif", "image/gif"), false);
		assert.equal(
			isAllowedUploadFile("payload.exe", "application/octet-stream"),
			false,
		);
		assert.equal(
			isAllowedUploadFile("report.docx", "application/x-msdownload"),
			false,
		);
	});
});
