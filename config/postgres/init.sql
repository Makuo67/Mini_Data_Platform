-- ============================================================
-- Mini Data Platform — PostgreSQL initialisation
-- Runs once on first container start via /docker-entrypoint-initdb.d
-- ============================================================

-- dataplatform database & user
CREATE USER dataplatform WITH PASSWORD 'dataplatform';
CREATE DATABASE dataplatform OWNER dataplatform;

-- Metabase uses the default 'airflow' superuser for its metadata DB
CREATE DATABASE metabase OWNER airflow;

-- Switch to the dataplatform database
\connect dataplatform

-- Sales fact table
CREATE TABLE IF NOT EXISTS sales (
    id            SERIAL PRIMARY KEY,
    order_id      VARCHAR(50)    NOT NULL,
    customer_id   VARCHAR(50)    NOT NULL,
    customer_name VARCHAR(100),
    product_id    VARCHAR(50),
    product_name  VARCHAR(100),
    category      VARCHAR(50),
    quantity      INTEGER,
    unit_price    NUMERIC(10, 2),
    total_amount  NUMERIC(10, 2),
    order_date    DATE,
    region        VARCHAR(50),
    status        VARCHAR(20),
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_order_id UNIQUE (order_id)
);

-- Pipeline bookkeeping
CREATE TABLE IF NOT EXISTS processed_files (
    id           SERIAL PRIMARY KEY,
    filename     VARCHAR(255) NOT NULL,
    record_count INTEGER,
    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_filename UNIQUE (filename)
);

-- Query-critical indexes
CREATE INDEX IF NOT EXISTS idx_sales_order_date   ON sales (order_date);
CREATE INDEX IF NOT EXISTS idx_sales_customer_id  ON sales (customer_id);
CREATE INDEX IF NOT EXISTS idx_sales_category     ON sales (category);
CREATE INDEX IF NOT EXISTS idx_sales_region       ON sales (region);

-- Grant access to the service account
GRANT ALL PRIVILEGES ON ALL TABLES    IN SCHEMA public TO dataplatform;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO dataplatform;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT ALL ON TABLES    TO dataplatform;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT ALL ON SEQUENCES TO dataplatform;
