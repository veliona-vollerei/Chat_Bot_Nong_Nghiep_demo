"""
convert_parquet.py — Xuất toàn bộ dữ liệu PostgreSQL & ChromaDB sang Parquet

Tính năng:
  1. PostgreSQL: Tự động truy vấn TẤT CẢ các bảng trong database (documents, chat_messages, chat_sessions, users, facts, kg_triples, v.v.)
     và xuất thành từng file <table_name>.parquet tương ứng.
  2. ChromaDB: Xuất toàn bộ vector chunks (bao gồm text, metadata, embedding) sang chroma_chunks.parquet.

Cách chạy:
  .venv\\Scripts\\Activate
  python convert_parquet.py
"""

import os
import sys
import json
from pathlib import Path

# Fix encoding cho terminal Windows
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

# pyrefly: ignore [missing-import]
from dotenv import load_dotenv
load_dotenv(BASE_DIR / ".env")

try:
    import pandas as pd
except ImportError:
    print("❌ Thiếu thư viện pandas. Chạy: pip install pandas pyarrow")
    sys.exit(1)

try:
    # pyrefly: ignore [missing-import]
    import pyarrow  # noqa
except ImportError:
    print("❌ Thiếu thư viện pyarrow. Chạy: pip install pyarrow")
    sys.exit(1)

OUTPUT_DIR = BASE_DIR / "data" / "parquet"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# ══════════════════════════════════════════════════════════════════
# 1. Xuất tất cả các bảng từ PostgreSQL
# ══════════════════════════════════════════════════════════════════

def export_all_postgres_tables() -> dict:
    """Tự động tìm và xuất TẤT CẢ các bảng trong PostgreSQL sang Parquet."""
    import psycopg2
    import psycopg2.extras

    pg_url = (
        f"postgresql://{os.getenv('POSTGRES_USER','postgres')}:"
        f"{os.getenv('POSTGRES_PASSWORD','')}@"
        f"{os.getenv('POSTGRES_HOST','localhost')}:"
        f"{os.getenv('POSTGRES_PORT','5432')}/"
        f"{os.getenv('POSTGRES_DB','chatbot_nongnghiep')}"
    )

    stats = {}

    try:
        conn = psycopg2.connect(pg_url)
        with conn.cursor() as cur:
            # Lấy danh sách các bảng trong schema 'public'
            cur.execute("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
                ORDER BY table_name;
            """)
            tables = [r[0] for r in cur.fetchall()]

        if not tables:
            print("  ⚠️ Không tìm thấy bảng nào trong PostgreSQL.")
            conn.close()
            return stats

        print(f"  📌 Tìm thấy {len(tables)} bảng trong PostgreSQL: {', '.join(tables)}\n")

        for table in tables:
            try:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute(f"SELECT * FROM {table};")
                    rows = cur.fetchall()

                if not rows:
                    print(f"  ⚠️  [PostgreSQL] Bảng '{table}' trống (0 dòng) — tạo parquet rỗng cấu hình cột.")
                    # Vẫn có thể lấy schema cột
                    with conn.cursor() as cur:
                        cur.execute(f"SELECT * FROM {table} LIMIT 0;")
                        colnames = [desc[0] for desc in cur.description]
                    df = pd.DataFrame(columns=colnames)
                else:
                    df = pd.DataFrame([dict(r) for r in rows])

                    # Xử lý các kiểu dữ liệu không tương thích mặc định với Parquet (datetime, dict/json)
                    for col in df.columns:
                        # Convert datetime / timestamp / json objects -> string/json
                        sample_vals = df[col].dropna()
                        if not sample_vals.empty:
                            first_val = sample_vals.iloc[0]
                            if isinstance(first_val, (dict, list)):
                                df[col] = df[col].apply(lambda x: json.dumps(x, ensure_ascii=False) if x is not None else None)
                            elif hasattr(first_val, 'isoformat'):
                                df[col] = df[col].astype(str)

                out_path = OUTPUT_DIR / f"{table}.parquet"
                df.to_parquet(out_path, engine="pyarrow", index=False)
                print(f"  ✅ [PostgreSQL] {table}.parquet — {len(df):,} dòng × {len(df.columns)} cột → {out_path.name}")
                stats[table] = len(df)

            except Exception as te:
                print(f"  ❌ Lỗi khi xuất bảng '{table}': {te}")
                stats[table] = 0

        conn.close()

    except Exception as e:
        print(f"  ❌ Không thể kết nối PostgreSQL: {e}")

    return stats


# ══════════════════════════════════════════════════════════════════
# 2. Xuất ChromaDB → chroma_chunks.parquet
# ══════════════════════════════════════════════════════════════════

def export_chroma_chunks() -> int:
    """Xuất toàn bộ chunks từ ChromaDB collection sang Parquet."""
    try:
        # pyrefly: ignore [missing-import]
        import chromadb
        # pyrefly: ignore [missing-import]
        from chromadb.config import Settings
    except ImportError:
        print("  ❌ Thiếu thư viện chromadb. Chạy: pip install chromadb")
        return 0

    chroma_dir = str(BASE_DIR / "chroma_db")
    collection_name = os.getenv("CHROMA_COLLECTION_NAME", "nongnghiep_chunks")

    try:
        client = chromadb.PersistentClient(
            path=chroma_dir,
            settings=Settings(anonymized_telemetry=False)
        )
        collection = client.get_collection(name=collection_name)
        total = collection.count()

        if total == 0:
            print("  ⚠️ ChromaDB collection rỗng — bỏ qua.")
            return 0

        print(f"  📦 Đang tải {total:,} chunks từ ChromaDB...")

        result = collection.get(
            include=["documents", "metadatas", "embeddings"],
            limit=total + 1000,
        )

        ids         = result.get("ids", [])
        documents   = result.get("documents", [])
        metadatas   = result.get("metadatas", [])
        embeddings  = result.get("embeddings")

        has_embeddings = embeddings is not None and len(embeddings) > 0

        rows = []
        for i, chunk_id in enumerate(ids):
            meta = metadatas[i] if metadatas else {}
            row = {
                "chunk_id":           chunk_id,
                "chunk_text":         documents[i] if documents else "",
                "source":             meta.get("source", ""),
                "topic":              meta.get("topic", ""),
                "crop":               meta.get("crop", ""),
                "season":             meta.get("season", ""),
                "soil_type":          meta.get("soil_type", ""),
                "source_document_id": meta.get("source_document_id", ""),
                "chunk_index":        meta.get("chunk_index", None),
                "total_chunks":       meta.get("total_chunks", None),
            }
            if has_embeddings and i < len(embeddings):
                emb = embeddings[i]
                try:
                    if hasattr(emb, "tolist"):
                        emb_list = emb.tolist()
                    else:
                        emb_list = list(emb)
                    row["embedding_json"] = json.dumps(
                        [round(float(x), 6) for x in emb_list]
                    )
                except Exception:
                    row["embedding_json"] = None
            else:
                row["embedding_json"] = None
            rows.append(row)

        df = pd.DataFrame(rows)

        out_path = OUTPUT_DIR / "chroma_chunks.parquet"
        df.to_parquet(out_path, engine="pyarrow", index=False)
        print(f"  ✅ [ChromaDB] chroma_chunks.parquet — {len(df):,} dòng × {len(df.columns)} cột → {out_path.name}")
        return len(df)

    except Exception as e:
        print(f"  ❌ Lỗi export ChromaDB: {e}")
        return 0


# ══════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 65)
    print("  📊 XUẤT TOÀN BỘ DỮ LIỆU (POSTGRESQL + CHROMADB) → PARQUET")
    print("=" * 65)
    print(f"  Thư mục đầu ra: {OUTPUT_DIR}\n")

    print("▶ [1/2] Đang quét và xuất tất cả các bảng trong PostgreSQL...")
    pg_stats = export_all_postgres_tables()

    print("\n▶ [2/2] Đang xuất ChromaDB vector collection...")
    chroma_count = export_chroma_chunks()

    print("\n" + "=" * 65)
    print("  ✅ HOÀN TẤT XUẤT PARQUET")
    print("  -------------------------------------------------------------")
    print("  [PostgreSQL Tables]")
    for t_name, count in pg_stats.items():
        print(f"    - {t_name:<25}: {count:,} dòng -> {t_name}.parquet")
    print(f"  [ChromaDB Collection]")
    print(f"    - chroma_chunks            : {chroma_count:,} dòng -> chroma_chunks.parquet")
    print("  -------------------------------------------------------------")
    print(f"  📁 Xem tất cả file Parquet tại: {OUTPUT_DIR}")
    print("=" * 65)