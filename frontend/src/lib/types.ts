// Shapes of the FastAPI responses this UI uses (see the backend OpenAPI schema).

export type DocumentStatus = "uploaded" | "queued" | "processing" | "completed" | "failed";
export type JobStatus = "pending" | "queued" | "processing" | "retrying" | "completed" | "failed";
export type SearchMode = "hybrid" | "semantic" | "keyword";

export interface User {
  id: string;
  email: string;
  role: "user" | "admin";
  is_active: boolean;
  created_at: string;
  updated_at: string;
  is_demo?: boolean;
  demo?: DemoStatus | null;
}

export interface DemoStatus {
  questions_used: number;
  questions_limit: number;
  questions_remaining: number;
  uploads_used: number;
  uploads_limit: number;
  max_upload_bytes: number;
  allowed_extensions: string[];
  expires_at: string | null;
}

export interface DocumentItem {
  id: string;
  original_filename: string;
  content_type: string;
  file_size: number;
  checksum_sha256: string;
  status: DocumentStatus;
  created_at: string;
  updated_at: string;
  /** Generated from the document text after processing; null = use generic suggestions. */
  suggested_questions?: string[] | null;
}

export interface Page<T> {
  total: number;
  page: number;
  page_size: number;
  items: T[];
}

export interface ProcessingJob {
  id: string;
  status: JobStatus;
  attempts: number;
  stage: string | null;
  error_message: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface DocumentStatusResponse {
  document_id: string;
  status: DocumentStatus;
  job: ProcessingJob | null;
  chunk_count: number;
}

export interface UploadResponse {
  id: string;
  status: DocumentStatus;
  job_id: string;
  job_status: JobStatus;
}

export interface UploadPolicy {
  max_upload_size_bytes: number;
  allowed_extensions: string[];
  allowed_content_types: string[];
}

export interface SearchResult {
  chunk_id: string;
  document_id: string;
  filename: string;
  chunk_index: number;
  text: string;
  page_start: number | null;
  page_end: number | null;
  char_start: number;
  char_end: number;
  token_count: number;
  score: number;
  similarity: number | null;
  semantic_rank: number | null;
  keyword_rank: number | null;
}

export interface SearchResponse {
  query: string;
  mode: SearchMode;
  reranked: boolean;
  results: SearchResult[];
}

export interface Citation {
  /** The [n] marker in the answer text. */
  number: number;
  source_id: string;
  chunk_id: string;
  document_id: string;
  filename: string;
  chunk_index: number;
  page_start: number | null;
  page_end: number | null;
  char_start: number;
  char_end: number;
  snippet: string;
}

export interface AskResponse {
  answer: string;
  insufficient_evidence: boolean;
  citations: Citation[];
  sources_considered: number;
  model: string | null;
  warnings: string[];
  partial?: boolean;
  missing_information?: string | null;
  insufficient_reason?: "below_threshold" | "model_declined" | "parse_failed" | "no_valid_citations" | null;
  prompt_version?: string;
  demo_questions_remaining?: number | null;
}

export interface ApiErrorBody {
  error?: {
    code?: string;
    message?: string;
    request_id?: string | null;
    details?: Array<{ limit?: string; [key: string]: unknown }>;
  };
}
