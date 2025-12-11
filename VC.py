import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta
import hashlib, binascii, os, io, base64

# ---------------- CONFIG ----------------
st.set_page_config(page_title="Biomedical Dashboard", layout="wide")
INVENTORY_FILE = "biomedical_lab_inventory.xlsx"
USERS_FILE = "users.csv"
PBKDF2_ITER_DEFAULT = 200_000
DATE_FMT = "%Y-%m-%d"

if "active_tab" not in st.session_state:
    st.session_state["active_tab"] = 0

if not hasattr(st, "experimental_rerun"):
    st.experimental_rerun = st.rerun

def load_users(filepath=USERS_FILE):
    if not os.path.exists(filepath):
        return pd.DataFrame(columns=["username", "salt", "hash", "iterations"])
    df = pd.read_csv(filepath, dtype=str)
    for c in ["username", "salt", "hash", "iterations"]:
        if c not in df.columns:
            df[c] = ""
    return df

def verify_password_pbkdf2(password, salt_hex, hash_hex, iterations):
    try:
        salt = binascii.unhexlify(salt_hex.encode("utf-8"))
    except Exception:
        salt = salt_hex.encode("utf-8")
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations))
    return binascii.hexlify(dk).decode("utf-8") == hash_hex

def add_user_to_csv(username, password, filepath=USERS_FILE, iterations=PBKDF2_ITER_DEFAULT):
    salt = binascii.hexlify(os.urandom(16)).decode("utf-8")
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), binascii.unhexlify(salt), iterations)
    hash_hex = binascii.hexlify(dk).decode("utf-8")
    row = {"username": username, "salt": salt, "hash": hash_hex, "iterations": str(iterations)}
    if os.path.exists(filepath):
        df = pd.read_csv(filepath, dtype=str)
        if username in df.get("username", pd.Series(dtype=str)).tolist():
            raise ValueError("Username already exists.")
        df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    else:
        df = pd.DataFrame([row])
    df.to_csv(filepath, index=False)

def delete_user_from_csv(username, filepath=USERS_FILE):
    df = load_users(filepath)
    if username not in df["username"].values:
        raise ValueError("Username not found.")
    df = df[df["username"] != username].reset_index(drop=True)
    df.to_csv(filepath, index=False)

# INVENTORY LOADING (cached) 
@st.cache_data(ttl=600)
def load_inventory(path=INVENTORY_FILE):
    if not os.path.exists(path):
        cols = ["Item ID","Item Name","Category","Quantity","Unit","Reorder Level",
                "Supplier","Last Restocked","Expiry Date","Storage Location","Remarks"]
        return pd.DataFrame(columns=cols)
    df = pd.read_excel(path, engine="openpyxl", dtype=str)
    if "Quantity" in df.columns:
        df["Quantity"] = pd.to_numeric(df["Quantity"], errors="coerce").fillna(0).astype(int)
    if "Reorder Level" in df.columns:
        df["Reorder Level"] = pd.to_numeric(df["Reorder Level"], errors="coerce").fillna(0).astype(int)
    default_cols = ["Item ID","Item Name","Category","Quantity","Unit","Reorder Level",
                    "Supplier","Last Restocked","Expiry Date","Storage Location","Remarks"]
    for c in default_cols:
        if c not in df.columns:
            df[c] = "" if c not in ["Quantity","Reorder Level"] else 0
    return df[default_cols]

# LOGS
def log_action(user, action_desc, details=""):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    details_clean = str(details).replace("\n", " ").replace("\r", " ")
    entry = f"{now}, {user}, {action_desc}"
    if details_clean:
        entry += f", {details_clean}"
    entry += "\n"
    with open("audit_log.csv", "a", encoding="utf-8") as f:
        f.write(entry)

def is_admin_user(username):
    df = load_users()
    if df.empty:
        return False
    return username == df.iloc[0]["username"]

def next_item_id(df):
    existing = df.get("Item ID", pd.Series(dtype=str)).astype(str).tolist()
    nums = []
    for v in existing:
        try:
            if isinstance(v, str) and v.upper().startswith("LAB") and v[3:].isdigit():
                nums.append(int(v[3:]))
        except Exception:
            pass
    n = max(nums) + 1 if nums else 1
    return f"LAB{n:03d}"

def save_inventory(df, path=INVENTORY_FILE, action_desc="Updated inventory", details=""):
    df.to_excel(path, index=False, engine="openpyxl")
    st.session_state["inventory_df"] = df.copy()
    user = st.session_state.get("username", "Unknown User")
    log_action(user, action_desc, details)
    try:
        st.toast("✅ Inventory updated!", icon="📦")
    except Exception:
        st.success("Inventory updated.")
    st.experimental_rerun()

# -Chart helpers
@st.cache_data(ttl=300, show_spinner=False)
def make_bar_fig(df_json, x, y, color_scale=None, text_col=None, title=None, margin_top=30):
    df_local = pd.read_json(df_json)
    if x not in df_local.columns or y not in df_local.columns:
        return None
    if color_scale:
        fig = px.bar(df_local, x=x, y=y, color=y, color_continuous_scale=color_scale, text=text_col, title=title)
    else:
        fig = px.bar(df_local, x=x, y=y, text=text_col, title=title)
    fig.update_layout(transition_duration=0, margin=dict(t=margin_top, b=30, l=20, r=20))
    try:
        fig.update_traces(textposition="outside")
    except Exception:
        pass
    return fig

@st.cache_data(ttl=300, show_spinner=False)
def make_pie_fig(df_json, names_col, values_col, title=None):
    df_local = pd.read_json(df_json)
    if names_col not in df_local.columns or values_col not in df_local.columns:
        return None
    fig = px.pie(df_local, names=names_col, values=values_col, title=title)
    fig.update_layout(transition_duration=0, margin=dict(t=30, b=30, l=20, r=20))
    return fig

# Header
def get_base64_of_image(image_path):
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode()

logo_html = ""
if os.path.exists("nhrc_logo.png"):
    logo_base64 = get_base64_of_image("nhrc_logo.png")
    logo_html = f"<img src='data:image/png;base64,{logo_base64}' width='170' style='display:block;margin:0 auto 8px auto;'>"

PALETTES = {
    "overview": {"bg": "#E8F8F5", "card_colors": ["#1ABC9C","#27AE60","#FF4C4C","#F39C12"]},
    "category": {"bg": "#EAF2F8", "scale": "Blues"},
    "expiry": {"bg": "#FFF3E0", "scale": "YlOrRd"},
    "manage": {"bg": "#FFF0E6", "scale": "Oranges"},
    "users": {"bg": "#F5EAF8", "scale": "Purples"}
}

st.markdown(
    f"""
    <div style='text-align:center;padding:6px 0 12px 0;background:transparent;'>
        {logo_html}
        <h3 style='margin:0;color:#6A0DAD;'>Navrongo Health Research Centre</h3>
        <h4 style='margin:0;color:#6A0DAD;'>Biomedical Science Department</h4>
        <h6 style='margin:6px 0 0 0;color:#6A0DAD;'>Dr. Victor Asoala – Head of Department</h6>
    </div>
    <hr style='border:1px solid rgba(0,0,0,0.08);margin-bottom:18px;'>
    """,
    unsafe_allow_html=True
)

# ---------------- LOGIN ----------------
def login_ui():
    st.sidebar.title("🔐 Login")
    username = st.sidebar.text_input("Username")
    password = st.sidebar.text_input("Password", type="password")
    login_btn = st.sidebar.button("Login")
    if login_btn:
        try:
            users_df = load_users()
        except Exception as e:
            st.sidebar.error(f"Error reading users: {e}")
            return False, None
        row = users_df[users_df["username"] == username]
        if row.empty:
            st.sidebar.error("Invalid username or password.")
            return False, None
        row = row.iloc[0]
        ok = verify_password_pbkdf2(password, row["salt"], row["hash"], int(row["iterations"]))
        if ok:
            st.session_state["username"] = username
            st.sidebar.success(f"Signed in as {username}")
            return True, username
        else:
            st.sidebar.error("Invalid username or password.")
            return False, None
    return False, None

# enforce login
if "username" not in st.session_state:
    logged_in, username = login_ui()
    if not logged_in:
        st.info("Please log in from the sidebar to view or manage inventory.")
        st.stop()
else:
    username = st.session_state["username"]
    st.sidebar.write(f"Signed in as **{username}**")
    if st.sidebar.button("Logout"):
        del st.session_state["username"]
        st.experimental_rerun()

# ---------------- LOAD DATA INTO SESSION ----------------
if "inventory_df" not in st.session_state:
    try:
        st.session_state["inventory_df"] = load_inventory()
    except Exception as e:
        st.error(f"Could not load inventory: {e}")
        st.stop()

df = st.session_state["inventory_df"].copy()

try:
    users_df = load_users()
except Exception:
    users_df = pd.DataFrame(columns=["username","salt","hash","iterations"])

admin_mode = is_admin_user(username)

# ---------------- NAV / STYLING ----------------
tab_names = ["🏠 Overview", "📊 Category Insights", "⏰ Expiry Monitor", "🛠 Manage Inventory", "👥 User Management"]
st.markdown("""
    <style>
    div[role='radiogroup'] {
        display:flex;
        justify-content:center;
        gap:18px;
        flex-wrap:wrap;
        margin-bottom:18px;
    }
    div[role='radiogroup'] label {
        background:#fff;
        border-radius:10px;
        padding:10px 18px;
        box-shadow:0 4px 10px rgba(0,0,0,0.08);
        transition:all .18s ease;
        font-weight:600;
        color:#2b2b2b;
        border:1px solid rgba(0,0,0,0.05);
    }
    div[role='radiogroup'] label:hover { transform: translateY(-3px) scale(1.02); box-shadow:0 8px 20px rgba(0,0,0,0.12); cursor:pointer }
    div[role='radiogroup'] input:checked + div { background:#fff !important; color:#2b2b2b !important; box-shadow:0 4px 10px rgba(0,0,0,0.08) !important }
    </style>
""", unsafe_allow_html=True)

selected_tab = st.radio(
    "Navigation",
    range(len(tab_names)),
    format_func=lambda i: tab_names[i],
    index=st.session_state.get("active_tab", 0),
    horizontal=True,
    key="main_tab_radio",
    label_visibility="collapsed"
)
st.session_state["active_tab"] = selected_tab

# ---------------- CACHED COMPUTATIONS ----------------
@st.cache_data(ttl=300, show_spinner=False)
def get_category_sums(in_df):
    if in_df.empty:
        return pd.DataFrame(columns=["Category", "Quantity"])
    return in_df.groupby("Category", dropna=False)["Quantity"].sum().reset_index().sort_values("Quantity", ascending=False)

@st.cache_data(ttl=300, show_spinner=False)
def get_category_counts(in_df):
    if in_df.empty:
        return pd.DataFrame(columns=["Category", "Count"])
    vc = in_df["Category"].value_counts(dropna=False).reset_index()
    vc.columns = ["Category", "Count"]
    return vc

@st.cache_data(ttl=300, show_spinner=False)
def get_supplier_counts(in_df):
    if in_df.empty:
        return pd.DataFrame(columns=["Supplier", "Count"])
    sup = in_df["Supplier"].fillna("Unknown").value_counts().reset_index()
    sup.columns = ["Supplier", "Count"]
    return sup

# Helper to display plotly charts with consistent config
def render_plotly(fig):
    if fig is None:
        st.info("Insufficient data for chart.")
        return
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False, "responsive": True})

# ---------------- TAB: OVERVIEW ----------------
if selected_tab == 0:
    theme = PALETTES["overview"]
    st.markdown(f"<div style='background:{theme['bg']};padding:12px;border-radius:10px;'>", unsafe_allow_html=True)
    st.markdown("<h4 style='text-align:center;margin-bottom:6px;'>Overview</h4>", unsafe_allow_html=True)

    low_stock_count = (df["Quantity"] <= df["Reorder Level"]).sum() if "Quantity" in df.columns and "Reorder Level" in df.columns else 0
    exp_df = df.copy()
    exp_df["Expiry Parsed"] = pd.to_datetime(exp_df["Expiry Date"], errors="coerce")
    soon_count = exp_df[exp_df["Expiry Parsed"] <= (datetime.today() + timedelta(days=90))].shape[0] if "Expiry Date" in exp_df.columns else 0

    card_items = [
        ("Distinct SKUs", df["Item ID"].nunique() if "Item ID" in df.columns else 0, theme["card_colors"][0]),
        ("Total Quantity", int(df["Quantity"].sum()) if "Quantity" in df.columns else 0, theme["card_colors"][1]),
        ("Low-stock Items", int(low_stock_count), theme["card_colors"][2]),
        ("Expiring ≤ 90 days", int(soon_count), theme["card_colors"][3])
    ]
    cols = st.columns(4, gap="large")
    for c, (label, value, color) in zip(cols, card_items):
        c.markdown(f"""<div style="background:{color};padding:12px;border-radius:10px;text-align:center;color:#fff;box-shadow:0 3px 8px rgba(0,0,0,0.08);">
                        <div style="font-size:24px;font-weight:700">{value}</div>
                        <div style="margin-top:6px;font-weight:700">{label}</div>
                      </div>""", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)
    st.markdown("---")

    # Charts
    c1, c2, c3 = st.columns(3)
    with c1:
        st.subheader("Quantity by Category")
        cat_sum = get_category_sums(df)
        if not cat_sum.empty:
            fig_cat = make_bar_fig(cat_sum.to_json(), x="Category", y="Quantity", color_scale="Viridis", text_col="Quantity")
            render_plotly(fig_cat)
        else:
            st.info("No category data available.")

    with c2:
        st.subheader("Items per Category")
        cat_count = get_category_counts(df)
        if not cat_count.empty:
            fig_count = make_bar_fig(cat_count.to_json(), x="Category", y="Count", color_scale="Blues", text_col="Count")
            render_plotly(fig_count)
        else:
            st.info("No data.")

    with c3:
        st.subheader("Supplier Distribution")
        sup_count = get_supplier_counts(df)
        if not sup_count.empty:
            fig_sup = make_pie_fig(sup_count.to_json(), names_col="Supplier", values_col="Count", title="Items by Supplier")
            render_plotly(fig_sup)
        else:
            st.info("No suppliers found.")

    with st.expander("📋 Inventory Snapshot (click to expand)"):
        st.dataframe(df.sort_values(["Category", "Item Name"]).reset_index(drop=True), use_container_width=True)

# ---------------- TAB: CATEGORY INSIGHTS ----------------
elif selected_tab == 1:
    theme = PALETTES["category"]
    st.markdown(f"<div style='background:{theme['bg']};padding:12px;border-radius:10px;'>", unsafe_allow_html=True)
    st.markdown("<h2 style='text-align:center;margin-bottom:6px;'>Category Insights</h2>", unsafe_allow_html=True)

    categories = ["All"] + sorted(df["Category"].dropna().unique().tolist()) if "Category" in df.columns else ["All"]
    sel_cat = st.selectbox("Select Category", categories, key="cat_insight_select")
    cat_df = df if sel_cat == "All" else df[df["Category"] == sel_cat]

    a,b,c = st.columns(3)
    with a:
        st.subheader("By Supplier")
        sup_count = get_supplier_counts(cat_df)
        if not sup_count.empty:
            fig = make_bar_fig(sup_count.to_json(), x="Supplier", y="Count", color_scale=theme["scale"], text_col="Count")
            render_plotly(fig)
        else:
            st.info("No supplier data for selection.")

    with b:
        st.subheader("By Storage Location")
        loc = cat_df["Storage Location"].fillna("Unknown").value_counts().reset_index() if not cat_df.empty else pd.DataFrame()
        if not loc.empty:
            loc.columns = ["Storage Location", "Count"]
            fig = make_bar_fig(loc.to_json(), x="Storage Location", y="Count", color_scale=theme["scale"], text_col="Count")
            render_plotly(fig)
        else:
            st.info("No storage data.")

    with c:
        st.subheader("Low-stock Items")
        if not cat_df.empty and "Quantity" in cat_df.columns and "Reorder Level" in cat_df.columns:
            low = cat_df[cat_df["Quantity"] <= cat_df["Reorder Level"]]
            if low.empty:
                st.info("No low-stock items in this selection.")
            else:
                st.dataframe(low[["Item ID","Item Name","Quantity","Reorder Level","Storage Location"]].reset_index(drop=True), use_container_width=True)
        else:
            st.info("Insufficient data to calculate low stock.")

    st.markdown("</div>", unsafe_allow_html=True)
    st.markdown("---")

    st.subheader("Item Breakdown within Category")
    item_qty = cat_df.groupby("Item Name")["Quantity"].sum().reset_index().sort_values("Quantity", ascending=False) if not cat_df.empty else pd.DataFrame()
    if not item_qty.empty:
        fig_items = make_bar_fig(item_qty.to_json(), x="Item Name", y="Quantity", color_scale="YlOrRd", text_col="Quantity")
        render_plotly(fig_items)
    else:
        st.info("No items in this category.")

    st.markdown("---")
    st.subheader("Quantity vs Reorder Level (per item)")
    if "Reorder Level" in cat_df.columns and not cat_df.empty:
        cmp_df = cat_df.groupby(["Item ID","Item Name"], as_index=False).agg({"Quantity":"sum","Reorder Level":"max"})
        # Build bar + line by creating two figures merged in Plotly express is less straightforward; we'll build bar and then add scatter manually
        fig_reorder = px.bar(cmp_df, x="Item Name", y="Quantity", text="Quantity", title="Quantity vs Reorder Level")
        fig_reorder.add_scatter(x=cmp_df["Item Name"], y=cmp_df["Reorder Level"], mode="lines+markers", name="Reorder Level")
        fig_reorder.update_layout(transition_duration=0, margin=dict(t=30, b=30, l=20, r=20))
        try:
            fig_reorder.update_traces(textposition="outside")
        except Exception:
            pass
        render_plotly(fig_reorder)
    else:
        st.info("Reorder data not available.")

    with st.expander("📋 Full list for this category"):
        st.dataframe(cat_df.reset_index(drop=True), use_container_width=True)

# ---------------- TAB: EXPIRY MONITOR ----------------
elif selected_tab == 2:
    theme = PALETTES["expiry"]
    st.markdown(f"<div style='background:{theme['bg']};padding:12px;border-radius:10px;'>", unsafe_allow_html=True)
    st.markdown("<h2 style='text-align:center;margin-bottom:6px;'>Expiry Monitor</h2>", unsafe_allow_html=True)

    exp_df = df.copy()
    exp_df["Expiry Parsed"] = pd.to_datetime(exp_df["Expiry Date"], errors="coerce")
    exp_df["Days to Expiry"] = (exp_df["Expiry Parsed"] - pd.Timestamp(datetime.today())).dt.days

    st.markdown("""
        <style>
        div[data-testid="stRadio"] > div { justify-content:center; gap:16px; flex-wrap:wrap; }
        </style>
    """, unsafe_allow_html=True)

    exp_filter = st.radio("Show", ("All with expiry dates", "Expired (<=0 days)", "Expiring <30 days", "Expiring <90 days"), horizontal=True, key="expiry_filter")

    if exp_filter == "All with expiry dates":
        show = exp_df[exp_df["Expiry Parsed"].notna()].copy()
    elif exp_filter == "Expired (<=0 days)":
        show = exp_df[exp_df["Days to Expiry"] <= 0].copy()
    elif exp_filter == "Expiring <30 days":
        show = exp_df[(exp_df["Days to Expiry"] > 0) & (exp_df["Days to Expiry"] <= 30)].copy()
    else:
        show = exp_df[(exp_df["Days to Expiry"] > 0) & (exp_df["Days to Expiry"] <= 90)].copy()

    bins = [-99999, 0, 30, 90, 365, 999999]
    labels = ["Expired", "<30 days", "30-90 days", "3-12 months", ">1 year"]
    exp_df["Expiry Status"] = pd.cut(exp_df["Days to Expiry"].fillna(999999), bins=bins, labels=labels)
    status_counts = exp_df["Expiry Status"].value_counts().reindex(labels).fillna(0).astype(int)

    scols = st.columns(len(labels))
    colors = ["#FF4C4C","#FF8A50","#FFD166","#FFA500","#8AC926"]
    for col, lab, cnt, colr in zip(scols, labels, status_counts.tolist(), colors):
        col.markdown(f"""<div style="background:{colr};padding:10px;border-radius:8px;text-align:center;color:white;">
                        <div style='font-size:16px;font-weight:800'>{cnt}</div>
                        <div style='font-weight:700'>{lab}</div>
                      </div>""", unsafe_allow_html=True)

    st.markdown("</div>", unsafe_allow_html=True)
    st.markdown("---")

    left, right = st.columns([2,1])
    with left:
        st.subheader("Expiry Status Overview")
        status_df = status_counts.reset_index()
        status_df.columns = ["Expiry Status","Count"]
        fig = make_bar_fig(status_df.to_json(), x="Expiry Status", y="Count", color_scale=theme["scale"], text_col="Count")
        render_plotly(fig)
    with right:
        st.subheader("Counts")
        st.write(f"Total items with expiry dates: {exp_df[exp_df['Expiry Parsed'].notna()].shape[0]}")
        st.write(f"Expired: {exp_df[exp_df['Days to Expiry'] <= 0].shape[0]}")
        st.write(f"Expiring in 30 days: {exp_df[(exp_df['Days to Expiry'] > 0) & (exp_df['Days to Expiry'] <= 30)].shape[0]}")
        st.write(f"Expiring in 90 days: {exp_df[(exp_df['Days to Expiry'] > 0) & (exp_df['Days to Expiry'] <= 90)].shape[0]}")

    st.markdown("---")
    st.subheader(f"Listing: {exp_filter}")
    if show.empty:
        st.info("No items match this filter.")
    else:
        with st.expander("📋 View list"):
            show_display = show[["Item ID","Item Name","Category","Quantity","Expiry Date","Days to Expiry","Storage Location","Supplier","Remarks"]].copy()
            show_display = show_display.sort_values("Days to Expiry")
            st.dataframe(show_display.reset_index(drop=True), use_container_width=True)

# ---------------- TAB: MANAGE INVENTORY ----------------
elif selected_tab == 3:
    theme = PALETTES["manage"]
    st.markdown(f"<div style='background:{theme['bg']};padding:12px;border-radius:10px;'>", unsafe_allow_html=True)
    st.markdown("<h2 style='text-align:center;margin-bottom:6px;'>Manage Inventory</h2>", unsafe_allow_html=True)

    manage_ops = ["➕ Add Item", "✏️ Edit Item", "🗑 Delete Item", "📤 Bulk Upload / Export"]
    op = st.radio("Operation", manage_ops, horizontal=True, key="manage_ops_radio")

    if op == "➕ Add Item":
        st.markdown("### ➕ Add New Item")
        with st.form("add_item_form"):
            new_id = next_item_id(df)
            new_name = st.text_input("Item Name", key="add_name")
            new_cat = st.text_input("Category", key="add_cat")
            new_qty = st.number_input("Quantity", min_value=0, value=0, key="add_qty")
            new_unit = st.text_input("Unit", value="Pieces", key="add_unit")
            new_reorder = st.number_input("Reorder Level", min_value=0, value=1, key="add_reorder")
            new_supplier = st.text_input("Supplier", key="add_supplier")
            new_rest = st.date_input("Last Restocked", value=datetime.today().date(), key="add_rest")
            new_exp = st.text_input("Expiry Date (YYYY-MM-DD) or leave blank", value="", key="add_exp")
            new_loc = st.text_input("Storage Location", key="add_loc")
            new_remarks = st.text_input("Remarks", key="add_remarks")
            submitted = st.form_submit_button("Add Item")
            if submitted:
                row = {
                    "Item ID": new_id,
                    "Item Name": new_name,
                    "Category": new_cat,
                    "Quantity": int(new_qty),
                    "Unit": new_unit,
                    "Reorder Level": int(new_reorder),
                    "Supplier": new_supplier,
                    "Last Restocked": new_rest.strftime(DATE_FMT),
                    "Expiry Date": new_exp if new_exp else "N/A",
                    "Storage Location": new_loc,
                    "Remarks": new_remarks
                }
                df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
                details = f"ItemID={new_id}; Name={new_name}; Qty={new_qty}; Unit={new_unit}; Reorder={new_reorder}; Category={new_cat}; Supplier={new_supplier}"
                save_inventory(df, action_desc=f"Added new item: {new_id} ({new_name})", details=details)

    elif op == "✏️ Edit Item":
        st.markdown("### ✏️ Edit Item")
        if df.empty:
            st.info("No items to edit.")
        else:
            sel_id = st.selectbox("Select Item ID", df["Item ID"].tolist(), key="edit_select")
            if sel_id:
                row = df[df["Item ID"] == sel_id].iloc[0]
                old_name = row["Item Name"]
                old_qty = int(row["Quantity"]) if pd.notna(row["Quantity"]) else 0
                old_reorder = int(row["Reorder Level"]) if pd.notna(row["Reorder Level"]) else 0
                old_remarks = str(row["Remarks"]) if pd.notna(row["Remarks"]) else ""

                with st.form(f"edit_form_{sel_id}"):
                    e_qty = st.number_input("Quantity", min_value=0, value=old_qty, key=f"e_qty_{sel_id}")
                    e_reorder = st.number_input("Reorder Level", min_value=0, value=old_reorder, key=f"e_reorder_{sel_id}")
                    e_remarks = st.text_input("Remarks", value=old_remarks, key=f"e_remarks_{sel_id}")
                    save_btn = st.form_submit_button("Save changes")
                    if save_btn:
                        df.loc[df["Item ID"] == sel_id, ["Quantity","Reorder Level","Remarks"]] = [int(e_qty), int(e_reorder), e_remarks]
                        changes = []
                        if old_qty != int(e_qty):
                            changes.append(f"Quantity: {old_qty} → {e_qty}")
                        if old_reorder != int(e_reorder):
                            changes.append(f"Reorder Level: {old_reorder} → {e_reorder}")
                        if old_remarks != e_remarks:
                            changes.append(f"Remarks: '{old_remarks}' → '{e_remarks}'")
                        details = "; ".join(changes) if changes else "No changes made"
                        save_inventory(df, action_desc=f"Edited item {sel_id} ({old_name})", details=details)

    elif op == "🗑 Delete Item":
        st.markdown("### 🗑 Delete Item")
        if df.empty:
            st.info("No items to delete.")
        else:
            del_id = st.selectbox("Select Item ID to delete", [""] + df["Item ID"].tolist(), key="del_select")
            if del_id:
                if st.button("Delete selected item"):
                    item_row = df[df["Item ID"] == del_id].iloc[0] if del_id in df["Item ID"].values else None
                    if item_row is not None:
                        item_name = item_row["Item Name"]
                        item_qty = int(item_row["Quantity"]) if pd.notna(item_row["Quantity"]) else 0
                        details = f"ItemID={del_id}; Name={item_name}; Qty={item_qty}"
                    else:
                        details = f"ItemID={del_id}"
                    df = df[df["Item ID"] != del_id].reset_index(drop=True)
                    save_inventory(df, action_desc=f"Deleted item: {del_id}", details=details)

    else:  # Bulk Upload / Export
        st.markdown("### 📤 Bulk Upload / Export")
        uploaded = st.file_uploader("Upload an .xlsx file to replace current inventory (must contain Item ID column)", type=["xlsx"])
        if uploaded is not None:
            try:
                new_df = pd.read_excel(uploaded, engine="openpyxl")
                st.write("Preview of uploaded file:")
                st.dataframe(new_df.head(), use_container_width=True)
                if st.button("Save uploaded inventory"):
                    if "Item ID" not in new_df.columns:
                        st.error("Uploaded file must contain 'Item ID' column.")
                    else:
                        rows = new_df.shape[0]
                        if "Quantity" in new_df.columns:
                            new_df["Quantity"] = pd.to_numeric(new_df["Quantity"], errors="coerce").fillna(0).astype(int)
                        if "Reorder Level" in new_df.columns:
                            new_df["Reorder Level"] = pd.to_numeric(new_df["Reorder Level"], errors="coerce").fillna(0).astype(int)
                        save_inventory(new_df, action_desc=f"Bulk inventory upload by {username}", details=f"Rows={rows}")
            except Exception as e:
                st.error(f"Could not read uploaded file: {e}")

        if st.button("Download current inventory (Excel)"):
            towrite = io.BytesIO()
            df.to_excel(towrite, index=False, engine="openpyxl")
            towrite.seek(0)
            st.download_button("📥 Click to download current inventory", data=towrite, file_name="biomedical_lab_inventory_current.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    st.markdown("</div>", unsafe_allow_html=True)

# ---------------- TAB: USER MANAGEMENT ----------------
elif selected_tab == 4:
    theme = PALETTES["users"]
    st.markdown(f"<div style='background:{theme['bg']};padding:12px;border-radius:10px;'>", unsafe_allow_html=True)
    st.markdown("<h2 style='text-align:center;margin-bottom:6px;'>User Management</h2>", unsafe_allow_html=True)

    if not admin_mode:
        st.warning("Only the admin can manage users.")
        st.stop()

    st.subheader("Existing users")
    st.dataframe(load_users().reset_index(drop=True), use_container_width=True)

    st.markdown("### Create new user")
    with st.form("create_user_form"):
        new_username = st.text_input("Username")
        new_password = st.text_input("Password", type="password")
        create_sub = st.form_submit_button("Create user")
        if create_sub:
            try:
                add_user_to_csv(new_username, new_password)
                log_action(username, f"Created new user: {new_username}", details="")
                st.success(f"User '{new_username}' created.")
                st.experimental_rerun()
            except Exception as e:
                st.error(f"Could not create user: {e}")

    st.markdown("### Delete user")
    users_list = load_users()["username"].tolist()
    choices = [u for u in users_list if u != username]
    sel_del = st.selectbox("Select user to delete", options=[""] + choices, key="del_user")
    if sel_del:
        if st.button("Delete selected user"):
            try:
                delete_user_from_csv(sel_del)
                log_action(username, f"Deleted user: {sel_del}", details="")
                st.success(f"User '{sel_del}' deleted.")
                st.experimental_rerun()
            except Exception as e:
                st.error(f"Could not delete user: {e}")

    st.markdown("</div>", unsafe_allow_html=True)

# ---------------- FOOTER / AUDIT LOG ----------------
if admin_mode and os.path.exists("audit_log.csv"):
    st.subheader("🧾 Audit Log (Recent Actions)")
    try:
        log_df = pd.read_csv("audit_log.csv", names=["Timestamp", "User", "Action", "Details"], header=None)
        if log_df.shape[1] < 4:
            log_df["Details"] = ""
    except Exception:
        log_df = pd.read_csv("audit_log.csv", names=["Timestamp", "User", "Action"], header=None)
        log_df["Details"] = ""
    st.dataframe(log_df.tail(50), use_container_width=True)

    with open("audit_log.csv", "rb") as f:
        st.download_button(
            label="📥 Download Full Audit Log (CSV)",
            data=f,
            file_name="audit_log.csv",
            mime="text/csv",
            use_container_width=True
        )

# ---------------- housekeeping ----------------
# Keep session from growing too large (retain original logic)
if len(st.session_state.keys()) > 100:
    for k in list(st.session_state.keys()):
        if k.startswith("plotly") or "temp" in k.lower():
            del st.session_state[k]

st.markdown(
    "<p style='text-align:center;font-size:13px;color:gray;margin-top:25px;'>"
    "© 2025 Navrongo Health Research Centre – Built by Fedelis Amenga-etego</p>",
    unsafe_allow_html=True
)


