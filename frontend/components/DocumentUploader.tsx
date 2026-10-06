"use client";

import { useEffect, useRef, useState } from "react";
import api from "@/lib/api";

const ACCEPTED_FILE_TYPES = [".pdf", ".doc", ".docx", ".txt"];

const ACCEPTED_MIME_TYPES = [
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/plain",
];

type Department = {
    id: number;
    name: string;
    description: string;
    created_at: string;
};

type DocumentItem = {
    id: number;
    title: string;
    file_type: string;
    status: string;
    department: number;
    uploaded_by: number;
    created_at: string;
};

type DocumentUploaderProps = {
    onFileSelected?: (file: File) => void;
};

export default function DocumentUploader({
    onFileSelected,
}: DocumentUploaderProps) {
    const inputRef = useRef<HTMLInputElement>(null);

    const [isDragging, setIsDragging] = useState(false);
    const [selectedFile, setSelectedFile] = useState<File | null>(null);
    const [error, setError] = useState("");

    const [departments, setDepartments] = useState<Department[]>([]);
    const [departmentsError, setDepartmentsError] = useState("");
    const [selectedDepartment, setSelectedDepartment] = useState("");

    const [isUploading, setIsUploading] = useState(false);
    const [uploadProgress, setUploadProgress] = useState(0);
    const [uploadSuccess, setUploadSuccess] = useState(false);

    const [documents, setDocuments] = useState<DocumentItem[]>([]);
    const [documentsError, setDocumentsError] = useState("");
    const [isLoadingDocuments, setIsLoadingDocuments] = useState(false);
    const [deletingDocumentId, setDeletingDocumentId] = useState<number | null>(
        null,
    );

    const fetchDepartments = async () => {
        try {
            setDepartmentsError("");

            const response = await api.get<Department[]>("/departments/");

            setDepartments(response.data);
        } catch (error) {
            console.error("Failed to fetch departments:", error);
            setDepartmentsError("Failed to load departments.");
        }
    };

    const fetchDocuments = async () => {
        try {
            setDocumentsError("");
            setIsLoadingDocuments(true);

            const response = await api.get<DocumentItem[]>("/documents/");

            setDocuments(response.data);
        } catch (error) {
            console.error("Failed to fetch documents:", error);
            setDocumentsError("Failed to load documents.");
        } finally {
            setIsLoadingDocuments(false);
        }
    };

    useEffect(() => {
        fetchDepartments();
        fetchDocuments();
    }, []);

    const validateFile = (file: File) => {
        const extension = `.${file.name.split(".").pop()?.toLowerCase()}`;

        const isValid =
            ACCEPTED_FILE_TYPES.includes(extension) &&
            ACCEPTED_MIME_TYPES.includes(file.type);

        if (!isValid) {
            setError("Only PDF, Word, and TXT files are allowed.");
            setSelectedFile(null);
            setUploadSuccess(false);
            return false;
        }

        setError("");
        setUploadSuccess(false);
        setSelectedFile(file);
        onFileSelected?.(file);

        return true;
    };

    const handleFileChange = (file: File | undefined) => {
        if (!file) {
            return;
        }

        validateFile(file);
    };

    const handleDragOver = (event: React.DragEvent<HTMLElement>) => {
        event.preventDefault();
        setIsDragging(true);
    };

    const handleDragLeave = () => {
        setIsDragging(false);
    };

    const handleDrop = (event: React.DragEvent<HTMLElement>) => {
        event.preventDefault();
        setIsDragging(false);

        const file = event.dataTransfer.files[0];

        handleFileChange(file);
    };

    const openFilePicker = () => {
        inputRef.current?.click();
    };

    const handleUpload = async () => {
        if (!selectedFile) {
            setError("Please select a file.");
            return;
        }

        if (!selectedDepartment) {
            setError("Please select a department.");
            return;
        }

        try {
            setError("");
            setUploadSuccess(false);
            setIsUploading(true);
            setUploadProgress(0);

            const formData = new FormData();

            formData.append("title", selectedFile.name);
            formData.append("file_path", selectedFile);
            formData.append("department", selectedDepartment);

            await api.post("/documents/", formData, {
                headers: {
                    "Content-Type": "multipart/form-data",
                },
                onUploadProgress: (progressEvent) => {
                    if (progressEvent.total) {
                        const progress = Math.round(
                            (progressEvent.loaded * 100) /
                                progressEvent.total,
                        );

                        setUploadProgress(progress);
                    }
                },
            });

            setUploadProgress(100);
            setUploadSuccess(true);

            await fetchDocuments();
        } catch (error) {
            console.error("Failed to upload document:", error);
            setError("Failed to upload document.");
        } finally {
            setIsUploading(false);
        }
    };

    const handleDelete = async (documentId: number) => {
        const shouldDelete = window.confirm(
            "Are you sure you want to delete this document?",
        );

        if (!shouldDelete) {
            return;
        }

        try {
            setDocumentsError("");
            setDeletingDocumentId(documentId);

            await api.delete(`/documents/${documentId}/delete/`);

            await fetchDocuments();
        } catch (error) {
            console.error("Failed to delete document:", error);
            setDocumentsError("Failed to delete document.");
        } finally {
            setDeletingDocumentId(null);
        }
    };

    const getDepartmentName = (departmentId: number) => {
        const department = departments.find(
            (item) => item.id === departmentId,
        );

        return department?.name ?? `Department ${departmentId}`;
    };

    const formatDate = (date: string) => {
        return new Date(date).toLocaleString();
    };

    return (
        <div className="w-full">
            <section
                aria-label="Document file upload area"
                onDragOver={handleDragOver}
                onDragLeave={handleDragLeave}
                onDrop={handleDrop}
                className={`rounded-xl border-2 border-dashed p-8 text-center transition ${
                    isDragging
                        ? "border-blue-600 bg-blue-50"
                        : "border-gray-300 bg-gray-50"
                }`}
            >
                <input
                    ref={inputRef}
                    type="file"
                    accept=".pdf,.doc,.docx,.txt"
                    className="hidden"
                    onChange={(event) =>
                        handleFileChange(event.target.files?.[0])
                    }
                />

                <div className="text-4xl">📄</div>

                <p className="mt-3 font-medium text-gray-700">
                    Drag & Drop your document here
                </p>

                <p className="mt-1 text-sm text-gray-500">or</p>

                <button
                    type="button"
                    onClick={openFilePicker}
                    disabled={isUploading}
                    className="mt-2 font-medium text-blue-600 hover:text-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
                >
                    click to select a file
                </button>

                <p className="mt-3 text-xs text-gray-400">
                    Supported formats: PDF, Word, TXT
                </p>
            </section>

            {selectedFile && (
                <div className="mt-4 rounded-lg bg-green-50 p-4">
                    <p className="text-sm font-medium text-green-800">
                        Selected file
                    </p>

                    <p className="mt-1 text-sm text-green-700">
                        {selectedFile.name}
                    </p>
                </div>
            )}

            {error && (
                <div className="mt-4 rounded-lg bg-red-50 p-4">
                    <p className="text-sm text-red-700">{error}</p>
                </div>
            )}

            {departments.length > 0 && (
                <div className="mt-4">
                    <label
                        htmlFor="department"
                        className="mb-2 block text-sm font-medium text-gray-700"
                    >
                        Department
                    </label>

                    <select
                        id="department"
                        className="w-full rounded-lg border border-gray-300 bg-white p-3 text-sm text-gray-700 focus:border-blue-500 focus:outline-none"
                        value={selectedDepartment}
                        onChange={(event) =>
                            setSelectedDepartment(event.target.value)
                        }
                        disabled={isUploading}
                    >
                        <option value="" disabled>
                            Select a department
                        </option>

                        {departments.map((department) => (
                            <option
                                key={department.id}
                                value={department.id}
                            >
                                {department.name}
                            </option>
                        ))}
                    </select>
                </div>
            )}

            {departmentsError && (
                <div className="mt-4 rounded-lg bg-red-50 p-4">
                    <p className="text-sm text-red-700">
                        {departmentsError}
                    </p>
                </div>
            )}

            {selectedFile && selectedDepartment && (
                <button
                    type="button"
                    onClick={handleUpload}
                    disabled={isUploading}
                    className="mt-4 w-full rounded-lg bg-blue-600 px-4 py-3 font-medium text-white transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
                >
                    {isUploading ? "Uploading..." : "Upload Document"}
                </button>
            )}

            {isUploading && (
                <div className="mt-4">
                    <div className="mb-2 flex items-center justify-between text-sm">
                        <span className="font-medium text-gray-700">
                            Uploading...
                        </span>

                        <span className="text-gray-500">
                            {uploadProgress}%
                        </span>
                    </div>

                    <div className="h-3 w-full overflow-hidden rounded-full bg-gray-200">
                        <div
                            className="h-full rounded-full bg-blue-600 transition-all duration-300"
                            style={{ width: `${uploadProgress}%` }}
                        />
                    </div>
                </div>
            )}

            {uploadSuccess && (
                <div className="mt-4 rounded-lg bg-green-50 p-4">
                    <p className="text-sm font-medium text-green-800">
                        Document uploaded successfully.
                    </p>
                </div>
            )}

            <section className="mt-10">
                <div className="mb-4 flex items-center justify-between">
                    <h2 className="text-xl font-semibold text-gray-800">
                        My Documents
                    </h2>

                    <button
                        type="button"
                        onClick={fetchDocuments}
                        disabled={isLoadingDocuments}
                        className="rounded-lg border border-gray-300 px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                        {isLoadingDocuments ? "Refreshing..." : "Refresh"}
                    </button>
                </div>

                {documentsError && (
                    <div className="mb-4 rounded-lg bg-red-50 p-4">
                        <p className="text-sm text-red-700">
                            {documentsError}
                        </p>
                    </div>
                )}

                <div className="overflow-x-auto rounded-xl border border-gray-200">
                    <table className="min-w-full divide-y divide-gray-200">
                        <thead className="bg-gray-50">
                            <tr>
                                <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">
                                    Title
                                </th>

                                <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">
                                    Department
                                </th>

                                <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">
                                    Status
                                </th>

                                <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">
                                    Uploaded At
                                </th>

                                <th className="px-4 py-3 text-right text-xs font-semibold uppercase tracking-wide text-gray-500">
                                    Action
                                </th>
                            </tr>
                        </thead>

                        <tbody className="divide-y divide-gray-200 bg-white">
                            {isLoadingDocuments && documents.length === 0 ? (
                                <tr>
                                    <td
                                        colSpan={5}
                                        className="px-4 py-8 text-center text-sm text-gray-500"
                                    >
                                        Loading documents...
                                    </td>
                                </tr>
                            ) : documents.length === 0 ? (
                                <tr>
                                    <td
                                        colSpan={5}
                                        className="px-4 py-8 text-center text-sm text-gray-500"
                                    >
                                        No documents found.
                                    </td>
                                </tr>
                            ) : (
                                documents.map((document) => (
                                    <tr key={document.id}>
                                        <td className="px-4 py-3 text-sm font-medium text-gray-800">
                                            {document.title}
                                        </td>

                                        <td className="px-4 py-3 text-sm text-gray-600">
                                            {getDepartmentName(
                                                document.department,
                                            )}
                                        </td>

                                        <td className="px-4 py-3 text-sm">
                                            <span
                                                className={`inline-flex rounded-full px-3 py-1 text-xs font-medium ${
                                                    document.status ===
                                                    "Indexed"
                                                        ? "bg-green-100 text-green-700"
                                                        : document.status ===
                                                            "Failed"
                                                          ? "bg-red-100 text-red-700"
                                                          : document.status ===
                                                              "Processing"
                                                            ? "bg-yellow-100 text-yellow-700"
                                                            : "bg-gray-100 text-gray-700"
                                                }`}
                                            >
                                                {document.status}
                                            </span>
                                        </td>

                                        <td className="px-4 py-3 text-sm text-gray-600">
                                            {formatDate(document.created_at)}
                                        </td>

                                        <td className="px-4 py-3 text-right">
                                            <button
                                                type="button"
                                                onClick={() =>
                                                    handleDelete(document.id)
                                                }
                                                disabled={
                                                    deletingDocumentId ===
                                                    document.id
                                                }
                                                className="rounded-lg px-3 py-2 text-sm font-medium text-red-600 hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-50"
                                            >
                                                {deletingDocumentId ===
                                                document.id
                                                    ? "Deleting..."
                                                    : "Delete"}
                                            </button>
                                        </td>
                                    </tr>
                                ))
                            )}
                        </tbody>
                    </table>
                </div>
            </section>
        </div>
    );
}