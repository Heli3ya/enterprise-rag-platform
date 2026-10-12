"use client";

import {
	type ChangeEvent,
	type DragEvent,
	useCallback,
	useEffect,
	useRef,
	useState,
} from "react";
import api from "@/lib/api";

type Department = {
	id: number;
	name: string;
};

type DocumentItem = {
	id: number;
	title: string;
	file_path?: string;
	file_name?: string;
	filename?: string;
	department?: number | string;
	department_name?: string;
	status?: string;
	file_size?: number;
	created_at?: string;
};

type ApiList<T> = T[] | { results?: T[] };

const ALLOWED_EXTENSIONS = [".pdf", ".doc", ".docx", ".txt"];

const ALLOWED_MIME_TYPES = [
	"application/pdf",
	"application/msword",
	"application/vnd.openxmlformats-officedocument.wordprocessingml.document",
	"text/plain",
];

function getErrorMessage(error: unknown): string {
	const err = error as {
		response?: {
			data?: {
				detail?: string;
				error?: string;
				message?: string;
				[key: string]: unknown;
			};
		};
		message?: string;
	};

	const data = err.response?.data;

	if (data?.detail && typeof data.detail === "string") {
		return data.detail;
	}

	if (data?.error && typeof data.error === "string") {
		return data.error;
	}

	if (data?.message && typeof data.message === "string") {
		return data.message;
	}

	if (data) {
		const firstValue = Object.values(data).find(
			(value) => typeof value === "string" || Array.isArray(value),
		);

		if (typeof firstValue === "string") {
			return firstValue;
		}

		if (Array.isArray(firstValue)) {
			return firstValue.map(String).join(" ");
		}
	}

	return err.message || "An unexpected error occurred.";
}

function getList<T>(data: ApiList<T>): T[] {
	if (Array.isArray(data)) {
		return data;
	}

	if (data && Array.isArray(data.results)) {
		return data.results;
	}

	return [];
}

function getFileName(document: DocumentItem): string {
	return (
		document.filename ||
		document.file_name ||
		document.file_path?.split(/[\\/]/).pop() ||
		document.title
	);
}

function formatFileSize(size?: number): string {
	if (size === undefined || size === null || size <= 0) {
		return "—";
	}

	if (size < 1024) {
		return `${size} B`;
	}

	if (size < 1024 * 1024) {
		return `${(size / 1024).toFixed(1)} KB`;
	}

	return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

function isAllowedFile(file: File): boolean {
	const lowerName = file.name.toLowerCase();
	const extensionAllowed = ALLOWED_EXTENSIONS.some((extension) =>
		lowerName.endsWith(extension),
	);

	const mimeAllowed = !file.type || ALLOWED_MIME_TYPES.includes(file.type);

	return extensionAllowed && mimeAllowed;
}

export default function DocumentUploader() {
	const fileInputRef = useRef<HTMLInputElement>(null);

	const [departments, setDepartments] = useState<Department[]>([]);
	const [documents, setDocuments] = useState<DocumentItem[]>([]);
	const [selectedFile, setSelectedFile] = useState<File | null>(null);
	const [selectedDepartment, setSelectedDepartment] = useState("");
	const [title, setTitle] = useState("");
	const [isDragging, setIsDragging] = useState(false);
	const [isLoadingDepartments, setIsLoadingDepartments] = useState(true);
	const [isLoadingDocuments, setIsLoadingDocuments] = useState(true);
	const [isUploading, setIsUploading] = useState(false);
	const [deletingId, setDeletingId] = useState<number | null>(null);
	const [uploadProgress, setUploadProgress] = useState(0);
	const [error, setError] = useState("");
	const [success, setSuccess] = useState("");

	const fetchDepartments = useCallback(async () => {
		setIsLoadingDepartments(true);

		try {
			const response = await api.get<ApiList<Department>>("/departments/");
			const departmentList = getList(response.data);

			setDepartments(departmentList);

			setSelectedDepartment((current) => {
				if (
					current &&
					departmentList.some((department) => String(department.id) === current)
				) {
					return current;
				}

				return "";
			});
		} catch (err: unknown) {
			setError(`Failed to load departments: ${getErrorMessage(err)}`);
		} finally {
			setIsLoadingDepartments(false);
		}
	}, []);

	const fetchDocuments = useCallback(async () => {
		setIsLoadingDocuments(true);

		try {
			const response = await api.get<ApiList<DocumentItem>>("/documents/");
			setDocuments(getList(response.data));
		} catch (err: unknown) {
			setError(`Failed to load documents: ${getErrorMessage(err)}`);
		} finally {
			setIsLoadingDocuments(false);
		}
	}, []);

	useEffect(() => {
		void fetchDepartments();
		void fetchDocuments();
	}, [fetchDepartments, fetchDocuments]);

	const handleFileSelection = useCallback((file: File | null) => {
		setError("");
		setSuccess("");

		if (!file) {
			setSelectedFile(null);
			return;
		}

		if (!isAllowedFile(file)) {
			setSelectedFile(null);
			setError("Only PDF, Word (.doc/.docx), and TXT files are allowed.");

			if (fileInputRef.current) {
				fileInputRef.current.value = "";
			}

			return;
		}

		setSelectedFile(file);

		setTitle((current) => {
			if (current.trim()) {
				return current;
			}

			return file.name.replace(/\.[^.]+$/, "");
		});
	}, []);

	const handleInputChange = (event: ChangeEvent<HTMLInputElement>) => {
		handleFileSelection(event.target.files?.[0] ?? null);
	};

	const handleDragOver = (event: DragEvent<HTMLButtonElement>) => {
		event.preventDefault();
		event.stopPropagation();
		setIsDragging(true);
	};

	const handleDragLeave = (event: DragEvent<HTMLButtonElement>) => {
		event.preventDefault();
		event.stopPropagation();
		setIsDragging(false);
	};

	const handleDrop = (event: DragEvent<HTMLButtonElement>) => {
		event.preventDefault();
		event.stopPropagation();
		setIsDragging(false);

		const file = event.dataTransfer.files?.[0];

		if (file) {
			handleFileSelection(file);
		}
	};

	const handleUpload = async () => {
		setError("");
		setSuccess("");

		if (!selectedFile) {
			setError("Please select a file before uploading.");
			return;
		}

		if (!selectedDepartment) {
			setError("Please select a department.");
			return;
		}

		const documentTitle = title.trim();

		if (!documentTitle) {
			setError("Please enter a document title.");
			return;
		}

		const formData = new FormData();
		formData.append("title", documentTitle);
		formData.append("file_path", selectedFile);
		formData.append("department", selectedDepartment);

		setIsUploading(true);
		setUploadProgress(0);

		try {
			await api.post("/documents/", formData, {
				onUploadProgress: (event) => {
					if (event.total && event.total > 0) {
						setUploadProgress(
							Math.min(100, Math.round((event.loaded / event.total) * 100)),
						);
					}
				},
			});

			setUploadProgress(100);
			setSuccess("Document uploaded successfully.");
			setSelectedFile(null);
			setTitle("");

			if (fileInputRef.current) {
				fileInputRef.current.value = "";
			}

			await fetchDocuments();
		} catch (err: unknown) {
			setError(`Upload failed: ${getErrorMessage(err)}`);
		} finally {
			setIsUploading(false);
		}
	};

	const handleDelete = async (documentId: number) => {
		const confirmed = window.confirm(
			"Are you sure you want to delete this document?",
		);

		if (!confirmed) {
			return;
		}

		setError("");
		setSuccess("");
		setDeletingId(documentId);

		try {
			await api.delete(`/documents/${documentId}/delete/`);
			setSuccess("Document deleted successfully.");
			await fetchDocuments();
		} catch (err: unknown) {
			setError(`Failed to delete document: ${getErrorMessage(err)}`);
		} finally {
			setDeletingId(null);
		}
	};

	return (
		<section className="space-y-8 rounded-xl bg-white p-6 shadow-sm">
			<div>
				<h2 className="text-xl font-semibold text-gray-900">Upload Document</h2>
				<p className="mt-1 text-sm text-gray-500">
					Upload a PDF, Word, or TXT document and assign it to a department.
				</p>
			</div>

			{error && (
				<div
					role="alert"
					className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700"
				>
					{error}
				</div>
			)}

			{success && (
				<div
					role="status"
					className="rounded-lg border border-green-200 bg-green-50 p-3 text-sm text-green-700"
				>
					{success}
				</div>
			)}

			<div className="space-y-5">
				<div>
					<label
						htmlFor="document-title"
						className="mb-2 block text-sm font-medium text-gray-700"
					>
						Document title
					</label>
					<input
						id="document-title"
						type="text"
						value={title}
						onChange={(event) => setTitle(event.target.value)}
						placeholder="Enter document title"
						disabled={isUploading}
						className="w-full rounded-lg border border-gray-300 px-4 py-2 text-gray-900 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100 disabled:bg-gray-100"
					/>
				</div>

				<div>
					<label
						htmlFor="document-department"
						className="mb-2 block text-sm font-medium text-gray-700"
					>
						Department
					</label>
					<select
						id="document-department"
						value={selectedDepartment}
						onChange={(event) => setSelectedDepartment(event.target.value)}
						disabled={isLoadingDepartments || isUploading}
						className="w-full rounded-lg border border-gray-300 bg-white px-4 py-2 text-gray-900 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100 disabled:bg-gray-100"
					>
						<option value="">
							{isLoadingDepartments
								? "Loading departments..."
								: "Select a department"}
						</option>

						{departments.map((department) => (
							<option key={department.id} value={department.id}>
								{department.name}
							</option>
						))}
					</select>

					{!isLoadingDepartments && departments.length === 0 && (
						<p className="mt-2 text-sm text-amber-700">
							No departments were found. Check the departments API.
						</p>
					)}
				</div>

				<div>
					<input
						ref={fileInputRef}
						type="file"
						accept=".pdf,.doc,.docx,.txt"
						onChange={handleInputChange}
						disabled={isUploading}
						className="sr-only"
						aria-label="Choose a document file"
					/>

					<button
						type="button"
						onClick={() => fileInputRef.current?.click()}
						onDragOver={handleDragOver}
						onDragLeave={handleDragLeave}
						onDrop={handleDrop}
						disabled={isUploading}
						className={`w-full rounded-xl border-2 border-dashed p-8 text-center transition-colors disabled:cursor-not-allowed disabled:opacity-60 ${
							isDragging
								? "border-blue-500 bg-blue-50"
								: "border-gray-300 bg-gray-50 hover:border-blue-400 hover:bg-blue-50"
						}`}
					>
						<span className="mb-3 block text-3xl" aria-hidden="true">
							📄
						</span>
						<span className="block font-medium text-gray-700">
							Drag and drop a file here
						</span>
						<span className="mt-2 block text-sm text-gray-500">
							or click to select a file
						</span>
						<span className="mt-2 block text-xs text-gray-400">
							Supported formats: PDF, DOC, DOCX, TXT
						</span>
					</button>
				</div>

				{selectedFile && (
					<div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-blue-200 bg-blue-50 p-4">
						<div className="min-w-0">
							<p className="text-sm font-medium text-gray-800">Selected file</p>
							<p className="break-all text-sm text-gray-600">
								{selectedFile.name}
							</p>
							<p className="mt-1 text-xs text-gray-500">
								{formatFileSize(selectedFile.size)}
							</p>
						</div>

						<button
							type="button"
							onClick={() => handleFileSelection(null)}
							disabled={isUploading}
							className="rounded-md px-3 py-1 text-sm text-red-600 hover:bg-red-100 disabled:opacity-50"
						>
							Remove
						</button>
					</div>
				)}

				{isUploading && (
					<div>
						<div className="mb-2 flex justify-between text-sm text-gray-600">
							<span>Uploading...</span>
							<span>{uploadProgress}%</span>
						</div>

						<div
							className="h-2.5 w-full overflow-hidden rounded-full bg-gray-200"
							role="progressbar"
							aria-label="Upload progress"
							aria-valuemin={0}
							aria-valuemax={100}
							aria-valuenow={uploadProgress}
						>
							<div
								className="h-full rounded-full bg-blue-600 transition-all duration-200"
								style={{ width: `${uploadProgress}%` }}
							/>
						</div>
					</div>
				)}

				<button
					type="button"
					onClick={handleUpload}
					disabled={
						isUploading ||
						isLoadingDepartments ||
						!selectedFile ||
						!selectedDepartment ||
						!title.trim()
					}
					className="w-full rounded-lg bg-blue-600 px-5 py-3 font-medium text-white transition-colors hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-gray-400"
				>
					{isUploading ? "Uploading..." : "Upload Document"}
				</button>
			</div>

			<div className="border-t border-gray-200 pt-6">
				<div className="mb-4 flex flex-wrap items-center justify-between gap-3">
					<div>
						<h3 className="text-lg font-semibold text-gray-900">
							Uploaded Documents
						</h3>
						<p className="mt-1 text-sm text-gray-500">
							View the documents available to your account.
						</p>
					</div>

					<button
						type="button"
						onClick={() => void fetchDocuments()}
						disabled={isLoadingDocuments}
						className="rounded-lg border border-gray-300 px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
					>
						{isLoadingDocuments ? "Refreshing..." : "Refresh"}
					</button>
				</div>

				{isLoadingDocuments ? (
					<p className="py-6 text-center text-sm text-gray-500">
						Loading documents...
					</p>
				) : documents.length === 0 ? (
					<p className="rounded-lg bg-gray-50 px-4 py-8 text-center text-sm text-gray-500">
						No documents found.
					</p>
				) : (
					<div className="overflow-x-auto">
						<table className="w-full min-w-[600px] border-collapse text-left text-sm">
							<thead>
								<tr className="border-b border-gray-200 text-gray-600">
									<th scope="col" className="px-3 py-3 font-medium">
										Document
									</th>
									<th scope="col" className="px-3 py-3 font-medium">
										Department
									</th>
									<th scope="col" className="px-3 py-3 font-medium">
										Status
									</th>
									<th scope="col" className="px-3 py-3 font-medium">
										Size
									</th>
									<th scope="col" className="px-3 py-3 font-medium">
										Actions
									</th>
								</tr>
							</thead>

							<tbody>
								{documents.map((document) => {
									const departmentName =
										document.department_name ||
										departments.find(
											(department) =>
												String(department.id) === String(document.department),
										)?.name ||
										"—";

									const status = document.status || "Pending";

									return (
										<tr
											key={document.id}
											className="border-b border-gray-100 last:border-0"
										>
											<td className="max-w-xs break-words px-3 py-4 font-medium text-gray-800">
												{document.title || getFileName(document)}
												{document.title &&
													getFileName(document) !== document.title && (
														<span className="mt-1 block text-xs font-normal text-gray-500">
															{getFileName(document)}
														</span>
													)}
											</td>

											<td className="px-3 py-4 text-gray-600">
												{departmentName}
											</td>

											<td className="px-3 py-4">
												<span
													className={`inline-flex rounded-full px-2.5 py-1 text-xs font-medium ${
														status.toLowerCase() === "indexed"
															? "bg-green-100 text-green-700"
															: status.toLowerCase() === "failed"
																? "bg-red-100 text-red-700"
																: "bg-amber-100 text-amber-700"
													}`}
												>
													{status}
												</span>
											</td>

											<td className="whitespace-nowrap px-3 py-4 text-gray-600">
												{formatFileSize(document.file_size)}
											</td>

											<td className="px-3 py-4">
												<button
													type="button"
													onClick={() => void handleDelete(document.id)}
													disabled={deletingId === document.id}
													className="rounded-md px-2 py-1 text-sm font-medium text-red-600 hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-50"
												>
													{deletingId === document.id
														? "Deleting..."
														: "Delete"}
												</button>
											</td>
										</tr>
									);
								})}
							</tbody>
						</table>
					</div>
				)}
			</div>
		</section>
	);
}
