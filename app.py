import os
import sqlite3
import sys
import pandas as pd
import streamlit as st


def ensure_db_initialized(db_path="idol_benefits.db"):
  if not os.path.exists(db_path) and os.path.exists("init_db.py"):
    import init_db

    init_db.init_database(db_path)


def main():
  st.set_page_config(
      page_title="Idol Benefit & Point Query System",
      page_icon="🎤",
      layout="wide",
  )
  db_path = "idol_benefits.db"
  ensure_db_initialized(db_path)

  if not os.path.exists(db_path):
    st.error(
        "Database not found. Please make sure `init_db.py` has been executed."
    )
    return

  conn = sqlite3.connect(db_path)
  st.title("🎤 台灣日系地下偶像拍券價格/特典點數使用規則查詢系統")
  st.caption(
      "Database Management Final Project: Python + SQLite (3NF Relational"
      " Database)"
  )

  df_cats = pd.read_sql("SELECT * FROM categories", conn)
  if df_cats.empty:
    st.warning("No data found in the database.")
    conn.close()
    return

  tab1, tab2, tab3 = st.tabs([
      "📋 Category & Idol Directory",
      "🔎 Advanced Search & Budget Filter",
      "🎁 First-Time Free & Special Offers",
  ])

  # === Tab 1: 依分類與偶像清單選擇查詢 ===
  with tab1:
    col_nav1, col_nav2 = st.columns([1, 2])
    with col_nav1:
      st.subheader("1. Select Category")
      cat_map = dict(zip(df_cats["category_name"], df_cats["category_id"]))
      selected_cat = st.radio("Choose category:", list(cat_map.keys()))

    df_idols = pd.read_sql(
        "SELECT * FROM idols WHERE category_id = ?",
        conn,
        params=(cat_map[selected_cat],),
    )

    with col_nav2:
      st.subheader("2. Select Idol / Group")
      if df_idols.empty:
        st.info("No records available in this category.")
        conn.close()
        return
      idol_map = dict(zip(df_idols["idol_name"], df_idols["idol_id"]))
      selected_idol = st.selectbox(
          f"Choose from {selected_cat}:", list(idol_map.keys())
      )

    idol_row = df_idols[df_idols["idol_id"] == idol_map[selected_idol]].iloc[0]

    st.divider()
    st.subheader(f"✨ {idol_row['idol_name']}")

    if pd.notna(idol_row["remarks"]) and str(idol_row["remarks"]).strip():
      st.error(f"**⚠️ Remarks / Alerts:** {idol_row['remarks']}")

    c1, c2, c3 = st.columns(3)
    with c1:
      st.info(
          f"**💰 Base Ticket Price**\n\n{idol_row['base_ticket_price'] or '(N/A)'}"
      )
    with c2:
      t_name = idol_row["ticket_name"] or "(None)"
      p_rule = idol_row["point_rule"] or "(None)"
      st.success(
          f"**🎟️ Ticket/Card Name: {t_name}**\n\n**Point Rule:**\n{p_rule}"
      )
    with c3:
      offers = idol_row.get("special_offers")
      st.warning(
          f"**🎁 Special Offers (※)**\n\n{offers if pd.notna(offers) and offers else '(None)'}"
      )

    df_items = pd.read_sql(
        """
            SELECT required_amount, unit, reward_content 
            FROM redemption_items 
            WHERE idol_id = ? 
            ORDER BY CASE WHEN required_amount IS NULL THEN 1 ELSE 0 END, required_amount ASC
        """,
        conn,
        params=(int(idol_row["idol_id"]),),
    )

    st.markdown("#### 🏆 Redemption Items & Tiers")
    if df_items.empty:
      st.caption("No redemption items available.")
    else:
      valid_amounts = df_items["required_amount"].dropna()
      if not valid_amounts.empty and int(valid_amounts.max()) > 0:
        max_pts = int(valid_amounts.max())
        unit_label = (
            df_items["unit"].dropna().iloc[0]
            if not df_items["unit"].dropna().empty
            else "pts/tickets"
        )
        user_pts = st.slider(
            f"💡 Filter by your current points/tickets ({unit_label}):",
            min_value=0,
            max_value=max_pts,
            value=max_pts,
        )
        filtered = df_items[
            df_items["required_amount"].isna()
            | (df_items["required_amount"] <= user_pts)
        ].copy()
      else:
        filtered = df_items.copy()

      def format_threshold(row):
        if pd.isna(row["required_amount"]):
          return "Special"
        return f"{int(row['required_amount'])} {row['unit'] or ''}".strip()

      filtered["Threshold"] = filtered.apply(format_threshold, axis=1)
      st.dataframe(
          filtered[["Threshold", "reward_content"]].rename(
              columns={"reward_content": "Reward Description"}
          ),
          use_container_width=True,
          hide_index=True,
      )

  # === Tab 2: 跨團進階搜尋與過濾 ===
  with tab2:
    st.subheader("🔎 Advanced Cross-Group Search & Filter")
    st.markdown(
        "Combine keywords and ticket price filters to search across all"
        " categories simultaneously."
    )

    col_s1, col_s2, col_s3 = st.columns([2, 1, 1])
    with col_s1:
      kw = st.text_input(
          "Keyword Search (e.g., 私物簽, 影片, 快速通關, 手寫信):", "私物簽"
      )
    with col_s2:
      category_filter = st.selectbox(
          "Filter by Category:", ["All Categories"] + list(cat_map.keys())
      )
    with col_s3:
      max_limit = st.number_input(
          "Max Points/Tickets (<= N, 0=Any):", min_value=0, value=0, step=5
      )

    sql_join = """
            SELECT 
                c.category_name AS 'Category',
                i.idol_name AS 'Name',
                COALESCE(i.ticket_name, '(None)') AS 'Ticket Type',
                r.required_amount AS 'Required',
                r.unit AS 'Unit',
                r.reward_content AS 'Reward Description',
                i.base_ticket_price AS 'Ticket Price'
            FROM redemption_items r
            JOIN idols i ON r.idol_id = i.idol_id
            JOIN categories c ON i.category_id = c.category_id
            WHERE r.reward_content LIKE ?
        """
    params = [f"%{kw}%"]

    if category_filter != "All Categories":
      sql_join += " AND c.category_name = ?"
      params.append(category_filter)

    if max_limit > 0:
      sql_join += " AND r.required_amount <= ?"
      params.append(max_limit)

    sql_join += " ORDER BY r.required_amount ASC"

    df_search = pd.read_sql(sql_join, conn, params=params)
    st.write(f"Found **{len(df_search)}** matching redemption items:")
    st.dataframe(df_search, use_container_width=True, hide_index=True)

  # === Tab 3: 初見無料與特別優惠速查 ===
  with tab3:
    st.subheader("🎁 First-Time Free & Volume Discount Offers")
    df_offers = pd.read_sql(
        """
            SELECT 
                c.category_name AS 'Category',
                i.idol_name AS 'Name',
                i.base_ticket_price AS 'Base Price',
                i.special_offers AS 'Special Offers (※)',
                COALESCE(i.remarks, '') AS 'Remarks'
            FROM idols i
            JOIN categories c ON i.category_id = c.category_id
            WHERE i.special_offers IS NOT NULL
        """,
        conn,
    )
    st.dataframe(df_offers, use_container_width=True, hide_index=True)

  conn.close()


if __name__ == "__main__":
  try:
    from streamlit.web import cli as stcli
    from streamlit import runtime

    if runtime.exists():
      main()
    else:
      sys.argv = ["streamlit", "run", os.path.abspath(__file__)]
      sys.exit(stcli.main())
  except ImportError:
    print("Please install required packages: pip install streamlit pandas")
