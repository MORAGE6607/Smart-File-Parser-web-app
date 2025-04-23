import streamlit as st
import pandas as pd
import xml.etree.ElementTree as ET
import gzip
import io
import zipfile
import filetype
import warnings
from docx import Document
import pandas.api.types as ptypes

st.set_page_config(page_title="Smart File Parser", layout="wide")
st.title("📂 Smart File Parser & Cleaner")

# === Utility Functions ===
def detect_file_type(uploaded_file):
    kind = filetype.guess(uploaded_file.read(261))
    uploaded_file.seek(0)
    if kind:
        return kind.mime
    name = uploaded_file.name.lower()
    if name.endswith(".xml"): return "text/xml"
    elif name.endswith(".csv"): return "text/csv"
    elif name.endswith(".xlsx"): return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    elif name.endswith(".gz"): return "application/gzip"
    elif name.endswith(".zip"): return "application/zip"
    elif name.endswith(".docx"): return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    elif name.endswith(".txt"): return "text/plain"
    return "unknown"

def decompress_gz_file(uploaded_file):
    with gzip.GzipFile(fileobj=uploaded_file) as f:
        return f.read().decode("utf-8", errors="replace")

def flatten_xml_element(elem, parent_tag='', depth=0, max_depth=5):
    data = {}
    if depth > max_depth: return data
    tag_prefix = f"{parent_tag}." if parent_tag else ""
    for child in elem:
        if len(child):
            data.update(flatten_xml_element(child, f"{tag_prefix}{child.tag}", depth + 1, max_depth))
        else:
            key = f"{tag_prefix}{child.tag}"
            data[key] = child.text.strip() if child.text else "NULL"
    return data

def get_most_repeated_tag(root):
    counts = {}
    for elem in root.iter():
        if list(elem): counts[elem.tag] = counts.get(elem.tag, 0) + 1
    return sorted(counts.items(), key=lambda x: -x[1])[0][0] if counts else root[0].tag

def extract_zip_files(file):
    dfs = {}
    with zipfile.ZipFile(file) as z:
        for name in z.namelist():
            if name.endswith((".csv", ".xlsx", ".xml", ".txt", ".docx")):
                content = z.read(name)
                dfs[name] = content
    return dfs

def read_docx(file_bytes):
    doc = Document(io.BytesIO(file_bytes))
    return pd.DataFrame([{"text": para.text} for para in doc.paragraphs if para.text.strip()])

def clean_text(text):
    if pd.isna(text): return "NULL"
    return str(text).replace("\n", " ").replace("\r", " ").replace('"', '""')

def clean_dataframe(df):
    for col in df.select_dtypes(include=["object"]).columns:
        df[col] = df[col].apply(clean_text)
    return df

def infer_column_type(col):
    try:
        sample = col.dropna().head(20)

        if sample.empty:
            return "Unknown"

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            date_parse_ratio = pd.to_datetime(sample, errors="coerce").notna().mean()

        if date_parse_ratio > 0.8:
            return "Date"

        if pd.to_numeric(sample, errors="coerce").notna().mean() > 0.8:
            return "Numeric"

        return "Text"
    except:
        return "Unknown"


# === File Upload ===
uploaded_file = st.file_uploader("Upload a file (.txt, .csv, .xlsx, .docx, .xml, .gz, .zip)", type=["txt", "csv", "xlsx", "docx", "xml", "gz", "zip"])
df = None

if uploaded_file:
    mime_type = detect_file_type(uploaded_file)
    try:
        if mime_type == "application/gzip":
            xml_str = decompress_gz_file(uploaded_file)
            root = ET.fromstring(xml_str)
            tag = get_most_repeated_tag(root)
            df = pd.DataFrame([flatten_xml_element(e) for e in root.findall(f".//{tag}")])

        elif mime_type == "text/xml":
            xml_str = uploaded_file.read().decode("utf-8", errors="replace")
            root = ET.fromstring(xml_str)
            tag = get_most_repeated_tag(root)
            df = pd.DataFrame([flatten_xml_element(e) for e in root.findall(f".//{tag}")])

        elif mime_type == "application/zip":
            files = extract_zip_files(uploaded_file)
            selected = st.selectbox("Select file from ZIP:", list(files.keys()))
            content = files[selected]
            if selected.endswith(".csv"):
                df = pd.read_csv(io.BytesIO(content))
            elif selected.endswith(".xlsx"):
                df = pd.read_excel(io.BytesIO(content))
            elif selected.endswith(".xml"):
                root = ET.fromstring(content.decode("utf-8"))
                tag = get_most_repeated_tag(root)
                df = pd.DataFrame([flatten_xml_element(e) for e in root.findall(f".//{tag}")])
            elif selected.endswith(".txt"):
                df = pd.read_csv(io.BytesIO(content), sep=None, engine="python")
            elif selected.endswith(".docx"):
                df = read_docx(content)

        elif mime_type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":
            sheets = pd.ExcelFile(uploaded_file).sheet_names
            sheet = st.selectbox("Select Excel Sheet:", sheets)
            df = pd.read_excel(uploaded_file, sheet_name=sheet)

        elif mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
            df = read_docx(uploaded_file.read())

        elif mime_type == "text/plain":
            df = pd.read_csv(uploaded_file, sep=None, engine="python")

        elif mime_type == "text/csv":
            df = pd.read_csv(uploaded_file)

        if df is not None:
            st.success(f"✅ Loaded {len(df)} rows and {len(df.columns)} columns.")

            # === Optional Preview ===
            if st.checkbox("🔍 Show first 20 rows of raw data"):
                st.dataframe(df.head(20))

            # === Column Selector with Hover Tooltips ===
            st.subheader("🧠 Select & Rename Columns (Hover for Summary)")
            selected_cols = st.multiselect("Select columns to keep", df.columns.tolist(), default=df.columns.tolist())

            rename_map = {}
            for col in selected_cols:
                with st.expander(f"📝 Rename & Inspect `{col}`", expanded=False):
                    col_type = infer_column_type(df[col])
                    st.markdown(f"- **Inferred Type**: `{col_type}`")
                    st.markdown(f"- **Missing**: `{df[col].isna().sum()}`")
                    st.markdown(f"- **Example**: `{df[col].dropna().iloc[0] if not df[col].dropna().empty else 'N/A'}`")
                    new_name = st.text_input(f"Rename column '{col}'", value=col, key=col)
                    rename_map[col] = new_name

            df = df[selected_cols].rename(columns=rename_map)

            # === Handle Missing Values ===
            st.subheader("🔧 Fill Missing Values")
            fill_value = st.selectbox("Fill missing values with:", ["NULL", "N/A", "0", "-"])
            df.fillna(fill_value, inplace=True)
            df = clean_dataframe(df)

            # === Final Preview ===
            st.subheader("📋 Final Preview")
            st.dataframe(df.head(20))

            # === Export Section ===
            st.subheader("📤 Export Cleaned Data")
            export_format = st.selectbox("Export format", ["CSV", "Excel (.xlsx)", "JSON"])

            if export_format == "CSV":
                st.download_button("⬇️ Download CSV", df.to_csv(index=False).encode("utf-8"), "cleaned_output.csv", "text/csv")

            elif export_format == "Excel (.xlsx)":
                buffer = io.BytesIO()
                with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
                    df.to_excel(writer, index=False)
                buffer.seek(0)
                st.download_button("⬇️ Download Excel", buffer, "cleaned_output.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

            elif export_format == "JSON":
                json_data = df.to_json(orient="records", indent=2)
                st.download_button("⬇️ Download JSON", json_data, "cleaned_output.json", "application/json")

    except Exception as e:
        st.error(f"❌ Error: {e}")
