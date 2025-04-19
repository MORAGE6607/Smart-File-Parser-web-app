import streamlit as st
import pandas as pd
import xml.etree.ElementTree as ET
import gzip
import io
import csv
import filetype

st.set_page_config(page_title="Smart File Parser & Cleaner", layout="centered")
st.title("Smart File Parser & Cleaner ")

# === Utility functions ===
def detect_file_type(uploaded_file):
    kind = filetype.guess(uploaded_file.read(261))
    uploaded_file.seek(0)
    if kind:
        return kind.mime
    name = uploaded_file.name.lower()
    if name.endswith(".xml"):
        return "text/xml"
    elif name.endswith(".csv"):
        return "text/csv"
    elif name.endswith(".xlsx"):
        return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    elif name.endswith(".gz"):
        return "application/gzip"
    return "unknown"

def decompress_gz_file(uploaded_file):
    with gzip.GzipFile(fileobj=uploaded_file) as f:
        buffer = io.BytesIO()
        while chunk := f.read(1024 * 1024):
            buffer.write(chunk)
        return buffer.getvalue().decode('utf-8', errors='replace')

def clean_text(text):
    if pd.isna(text):
        return 'NULL'
    return str(text).replace('\n', ' ').replace('\r', ' ').replace('"', '""')

def clean_dataframe(df):
    for col in df.select_dtypes(include=['object']).columns:
        df[col] = df[col].apply(clean_text)
    return df

def flatten_xml_element(elem, parent_tag='', depth=0, max_depth=5):
    data = {}
    if depth > max_depth:
        return data
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
        if list(elem):
            tag = elem.tag
            counts[tag] = counts.get(tag, 0) + 1
    if not counts:
        return root[0].tag if root else root.tag
    return sorted(counts.items(), key=lambda x: -x[1])[0][0]

# === File upload and processing ===
uploaded_file = st.file_uploader("Upload a file (.xml, .csv, .xlsx, .gz)", type=["xml", "csv", "xlsx", "gz"])
if uploaded_file:
    mime_type = detect_file_type(uploaded_file)
    try:
        if mime_type == "application/gzip":
            xml_str = decompress_gz_file(uploaded_file)
            root = ET.fromstring(xml_str)
            tag = get_most_repeated_tag(root)
            elements = root.findall(f".//{tag}")
            records = [flatten_xml_element(e) for e in elements]
            df = pd.DataFrame(records)
        elif mime_type == "text/xml":
            xml_str = uploaded_file.read().decode("utf-8", errors="replace")
            root = ET.fromstring(xml_str)
            tag = get_most_repeated_tag(root)
            elements = root.findall(f".//{tag}")
            records = [flatten_xml_element(e) for e in elements]
            df = pd.DataFrame(records)
        elif mime_type == "text/csv":
            df = pd.read_csv(uploaded_file)
        elif mime_type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":
            df = pd.read_excel(uploaded_file)
        else:
            st.error("Unsupported file format.")
            st.stop()

        st.success(f"Loaded {len(df)} records. Select columns to keep and rename:")
        selected_cols = st.multiselect("Select columns", df.columns.tolist(), default=df.columns.tolist())

        rename_map = {}
        for col in selected_cols:
            new_name = st.text_input(f"Rename column '{col}'", value=col)
            rename_map[col] = new_name

        final_df = df[selected_cols].rename(columns=rename_map)
        final_df = clean_dataframe(final_df)
        st.dataframe(final_df)

        csv = final_df.to_csv(index=False, quoting=csv.QUOTE_ALL).encode("utf-8")
        st.download_button("⬇️ Download Cleaned CSV", data=csv, file_name="cleaned_output.csv", mime="text/csv")

    except Exception as e:
        st.error(f"Error processing file: {e}")
