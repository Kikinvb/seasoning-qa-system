CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS app_user (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    username text UNIQUE NOT NULL,
    password_hash text NOT NULL,
    role text NOT NULL CHECK (role IN ('user','maintainer','admin')),
    active boolean NOT NULL DEFAULT true
);
CREATE TABLE IF NOT EXISTS login_session (
    token_hash text PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES app_user ON DELETE CASCADE,
    expires_at timestamptz NOT NULL DEFAULT now() + interval '12 hours'
);
CREATE TABLE IF NOT EXISTS kb_source (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_type text NOT NULL,
    origin_uri text,
    content_hash text UNIQUE,
    filename text,
    original_bytes bytea,
    parse_status text NOT NULL DEFAULT 'pending',
    parse_error text,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS kb_document (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id uuid NOT NULL REFERENCES kb_source ON DELETE CASCADE,
    external_doc_id text UNIQUE,
    title text NOT NULL,
    authority_level text,
    category text,
    standard_no text,
    version_label text,
    replaces_id uuid REFERENCES kb_document ON DELETE SET NULL,
    scope_text text,
    effective_date date,
    publish_date date,
    status text NOT NULL DEFAULT '页面未明示',
    source_format text NOT NULL,
    file_uri text,
    extra jsonb NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS kb_chunk (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id uuid NOT NULL REFERENCES kb_document ON DELETE CASCADE,
    external_entry_id text UNIQUE,
    clause_no text,
    heading_path text,
    content text NOT NULL,
    page_no integer,
    anchor text,
    position text NOT NULL,
    seq integer NOT NULL,
    keywords tsvector NOT NULL,
    embedding vector(512) NOT NULL
);
CREATE INDEX IF NOT EXISTS kb_document_source_idx ON kb_document(source_id);
CREATE INDEX IF NOT EXISTS kb_chunk_document_idx ON kb_chunk(document_id);
CREATE INDEX IF NOT EXISTS kb_chunk_keywords_idx ON kb_chunk USING gin(keywords);

CREATE TABLE IF NOT EXISTS chat_session (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    title text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS chat_message (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id uuid NOT NULL REFERENCES chat_session ON DELETE CASCADE,
    role text NOT NULL CHECK (role IN ('user', 'assistant')),
    content text NOT NULL,
    citations jsonb NOT NULL DEFAULT '[]'
);
ALTER TABLE chat_session ADD COLUMN IF NOT EXISTS user_id uuid REFERENCES app_user;

