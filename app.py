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
      page_title="台灣日系地下偶像拍券/特典點數使用規則查詢系統",
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
  st.title("🎤 台灣日系地下偶像拍券/特典點數使用規則查詢系統")

  df_cats = pd.read_sql("SELECT * FROM categories", conn)
  if df_cats.empty:
    st.warning("No data found in the database.")
    conn.close()
    return

  tab1, tab2, tab3 = st.tabs([
      "📋 偶像種類與清單選擇查詢",
      "🔎 特典兌換項目進階搜尋與篩選",
      "🎁 初見無料與特殊優惠查詢",
  ])

  # === Tab 1: 依分類與偶像清單選擇查詢 ===
  with tab1:
    col_nav1, col_nav2 = st.columns([1, 2])
    with col_nav1:
      st.subheader("1. 選擇偶像種類")
      cat_map = dict(zip(df_cats["category_name"], df_cats["category_id"]))
      selected_cat = st.radio("請選擇:", list(cat_map.keys()))

    df_idols = pd.read_sql(
        "SELECT * FROM idols WHERE category_id = ?",
        conn,
        params=(cat_map[selected_cat],),
    )

    with col_nav2:
      st.subheader("2. 選擇偶像名稱")
      if df_idols.empty:
        st.info("No records available in this category.")
        conn.close()
        return
      idol_map = dict(zip(df_idols["idol_name"], df_idols["idol_id"]))
      selected_idol = st.selectbox(
          f"選擇{selected_cat} (可點選進入下滑式清單or直接打字搜尋):",
          list(idol_map.keys()),
      )

    idol_row = df_idols[df_idols["idol_id"] == idol_map[selected_idol]].iloc[0]

    st.divider()
    st.subheader(f"✨ {idol_row['idol_name']}")

    if pd.notna(idol_row["remarks"]) and str(idol_row["remarks"]).strip():
      st.error(f"**⚠️備註:** {idol_row['remarks']}")

    c1, c2, c3 = st.columns(3)
    with c1:
      st.info(f"**💰拍券價格**\n\n{idol_row['base_ticket_price'] or '(N/A)'}")
    with c2:
      t_name = idol_row["ticket_name"] or "(None)"
      p_rule = idol_row["point_rule"] or "(None)"
      st.success(f"**🎟️特典券名稱: {t_name}**\n\n**兌換規則:**\n{p_rule}")
    with c3:
      offers = idol_row.get("special_offers")
      st.warning(
          f"**🎁特殊優惠**\n\n{offers if pd.notna(offers) and offers else '(None)'}"
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

    st.markdown("#### 🏆 特典券集點兌換項目")
    if df_items.empty:
      st.caption("暫無資料")
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
            f"💡 拖曳下方紅點至您目前的特典券點數，以進行兌換項目篩選 ({unit_label}):",
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
              columns={
                  "Threshold": "累積數量",
                  "reward_content": "兌換項目 (可點選下方表格看完整內容)",
              }
          ),
          use_container_width=True,
          hide_index=True,
      )

  # === Tab 2: 跨團進階搜尋與過濾 ===
  with tab2:
    st.subheader("🔎 特典兌換項目進階搜尋與篩選")
    st.markdown(
        "結合關鍵字、偶像種類與擁有的點數/張數上限，跨分類同步搜尋所有特典兌換項目。"
    )

    col_s1, col_s2, col_s3 = st.columns([2, 1, 1])
    with col_s1:
      kw = st.text_input(
          "關鍵字搜尋 (例如：手機拍, 影片, 私物簽, 快速通關, 手寫信, OFF會):",
          "私物簽",
      )
    with col_s2:
      category_filter = st.selectbox(
          "選擇偶像種類 (團體/個人):", ["全部"] + list(cat_map.keys())
      )
    with col_s3:
      max_limit = st.number_input(
          "擁有的最大值 (pt/張) (<= N):", min_value=0, value=0, step=1
      )

    sql_join = """
        SELECT 
            c.category_name AS '偶像種類',
            i.idol_name AS '名稱',
            COALESCE(i.ticket_name, '(無)') AS '特典券名稱',
            r.required_amount AS '需求數量',
            r.unit AS '單位',
            r.reward_content AS '特典兌換內容',
            i.base_ticket_price AS '基本拍券價格'
        FROM redemption_items r
        JOIN idols i ON r.idol_id = i.idol_id
        JOIN categories c ON i.category_id = c.category_id
        WHERE r.reward_content LIKE ?
    """
    params = [f"%{kw}%"]

    if category_filter != "全部":
      sql_join += " AND c.category_name = ?"
      params.append(category_filter)

    sql_join += " AND r.required_amount <= ?"
    params.append(max_limit)

    sql_join += " ORDER BY r.required_amount ASC"

    df_search = pd.read_sql(sql_join, conn, params=params)
    st.write(f"共找到 **{len(df_search)}** 筆符合條件的特典兌換項目 (欄位可左右移動且可從最上方調整各欄位的寬度，也可點選下方表格看完整內容)：")
    st.dataframe(df_search, use_container_width=True, hide_index=True)

  # === Tab 3: 初見無料與特別優惠速查 ===
  with tab3:
    st.subheader("🎁 初見無料與特殊優惠查詢")
    st.markdown(
        "欄位可左右移動且可從最上方調整各欄位的寬度，也可點選下方表格看完整內容"
    )
    
    df_offers = pd.read_sql(
        """
        SELECT 
            c.category_name AS '偶像種類',
            i.idol_name AS '名稱',
            i.special_offers AS '特殊優惠',
            i.base_ticket_price AS '基本拍券價格',
            COALESCE(i.remarks, '') AS '備註'
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
