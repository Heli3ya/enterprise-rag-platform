"use client";

import { useId } from "react";

/**
 * One empty-state component for both places that need it.
 *
 * `page` is the cold-start card on the dashboard: large, explained, and
 * impossible to miss. `inline` is the compact version rendered inside a
 * chat bubble when the assistant had nothing to answer from. They share
 * a structure so the two never drift apart, but the sizes differ
 * because a bubble is only 80% of the column wide.
 */

type EmptyStateAction = {
	label: string;
	onClick: () => void;
};

type EmptyStateProps = {
	variant?: "page" | "inline";
	title: string;
	description: string;
	primaryAction: EmptyStateAction;
	secondaryAction?: EmptyStateAction;
};

function DocumentIcon({ className }: { className?: string }) {
	return (
		<svg
			viewBox="0 0 48 48"
			fill="none"
			stroke="currentColor"
			strokeWidth={2}
			strokeLinecap="round"
			strokeLinejoin="round"
			aria-hidden="true"
			className={className}
		>
			<path d="M12 5h16l8 8v30H12z" />
			<path d="M28 5v8h8" />
			<path d="M20 27h8M24 23v8" />
		</svg>
	);
}

export default function EmptyState({
	variant = "page",
	title,
	description,
	primaryAction,
	secondaryAction,
}: EmptyStateProps) {
	const titleId = useId();

	if (variant === "inline") {
		return (
			<div
				role="status"
				className="rounded-lg border border-blue-200 bg-blue-50 p-4"
			>
				<p className="text-sm font-semibold text-gray-800">{title}</p>

				<p className="mt-1 text-sm leading-6 text-gray-600">{description}</p>

				<div className="mt-3 flex flex-wrap gap-2">
					<button
						type="button"
						onClick={primaryAction.onClick}
						className="rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-700"
					>
						{primaryAction.label}
					</button>

					{secondaryAction && (
						<button
							type="button"
							onClick={secondaryAction.onClick}
							className="rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50"
						>
							{secondaryAction.label}
						</button>
					)}
				</div>
			</div>
		);
	}

	return (
		<section
			aria-labelledby={titleId}
			className="rounded-xl border border-blue-200 bg-blue-50 p-6 sm:p-8"
		>
			<div className="flex flex-col items-center gap-5 text-center sm:flex-row sm:items-start sm:text-start">
				<span className="flex h-16 w-16 shrink-0 items-center justify-center rounded-full bg-white text-blue-600 shadow-sm">
					<DocumentIcon className="h-8 w-8" />
				</span>

				<div className="min-w-0 flex-1">
					<h2 id={titleId} className="text-xl font-semibold text-gray-900">
						{title}
					</h2>

					<p className="mt-2 text-sm leading-6 text-gray-600">{description}</p>

					<div className="mt-6 flex flex-col gap-3 sm:flex-row">
						<button
							type="button"
							onClick={primaryAction.onClick}
							className="rounded-xl bg-blue-600 px-6 py-3 text-base font-semibold text-white shadow-sm transition-colors hover:bg-blue-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-300"
						>
							{primaryAction.label}
						</button>

						{secondaryAction && (
							<button
								type="button"
								onClick={secondaryAction.onClick}
								className="rounded-xl border border-gray-300 bg-white px-6 py-3 text-base font-medium text-gray-700 transition-colors hover:bg-gray-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-300"
							>
								{secondaryAction.label}
							</button>
						)}
					</div>
				</div>
			</div>
		</section>
	);
}
