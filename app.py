import streamlit as st
import sqlite3
import pandas as pd
import time
import os
import sys
import subprocess

# --- 0. 環境修復：強制安裝 Playwright 套件與瀏覽器 ---
def ensure_playwright_installed():
    try:
        import playwright
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "playwright"])
    
    # 安裝 Chromium 瀏覽器
    subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"])

# 啟動時執行環境檢查
ensure_playwright_installed()

from playwright.sync_api import sync_playwright

# --- 1. 初始化環境與 CSS 注入 ---
UPLOAD_DIR = "uploaded_images"
if not os.path.exists(UPLOAD_DIR):
    os.makedirs(UPLOAD_DIR)

st.set_page_config(layout="wide", page_title="ヤフオク・メルカリ發送平台")

# CSS 注入：縮小上傳組件尺寸並隱藏標籤
st.markdown("""
    <style>
    .stFileUploader label {
        display: none;
    }
    .stFileUploader section {
        padding: 0px 5px !important;
        min-height: 40px !important;
    }
    div[data-testid="stExpander"] {
        border: none !important;
        box-shadow: none !important;
    }
    </style>
    """, unsafe_allow_html=True)

# --- 2. 資料庫功能 ---
def init_db():
    with sqlite3.connect('mercari.db') as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS items 
                        (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                         title TEXT, url TEXT, img_url TEXT, 
                         note TEXT, price TEXT, local_img TEXT, local_img2 TEXT,
                         is_done INTEGER DEFAULT 0)''')
        try:
            conn.execute("ALTER TABLE items ADD COLUMN is_done INTEGER DEFAULT 0")
        except:
            pass 

def update_db_simple(item_id, title, note, price, img1=None, img2=None):
    with sqlite3.connect('mercari.db') as conn:
        conn.execute("UPDATE items SET title=?, note=?, price=? WHERE id=?", (title, note, price, item_id))
        if img1: conn.execute("UPDATE items SET local_img=? WHERE id=?", (img1, item_id))
        if img2: conn.execute("UPDATE items SET local_img2=? WHERE id=?", (img2, item_id))
        conn.commit()

def update_status(item_id, status):
    with sqlite3.connect('mercari.db') as conn:
        conn.execute("UPDATE items SET is_done=? WHERE id=?", (status, item_id))
        conn.commit()

# --- 3. 彈窗大圖 ---
@st.dialog("發貨細節圖")
def show_full_image(img_path):
    if img_path and os.path.exists(img_path):
        st.image(img_path, use_container_width=True)
    else:
        st.warning("⚠️ 檔案不存在。")

# --- 4. 爬蟲核心 ---
def get_web_data(url):
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]
            )
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                locale="ja-JP"
            )
            page = context.new_page()
            page.goto(url, wait_until="load", timeout=30000)
            time.sleep(3) 
            
            title = "未知標題"
            img = ""

            if "yahoo.co.jp" in url:
                title_selectors = ['h1.Title__text', 'h1.ProductTitle__text', '.ProductTitle__title', 'h1']
                for s in title_selectors:
                    loc = page.locator(s).first
                    if loc.count() > 0:
                        t_text = loc.inner_text().strip(); title = t_text; break
                
                page.evaluate("window.scrollTo(0, 400)")
                time.sleep(1)
                img_selectors = ['div.ProductImage__image img', '.ProductImage__body img', '.Image__img']
                for s in img_selectors:
                    loc = page.locator(s).first
                    if loc.count() > 0:
                        i_src = loc.get_attribute('src'); img = i_src; break
            else:
                title = page.locator('h1').first.inner_text().strip()
                img = page.locator('div[data-testid="image-0"] img, img[alt="product-image"]').first.get_attribute('src')
                
            browser.close()
            return title, img
        except Exception as e:
            if 'browser' in locals(): browser.close()
            return f"抓取失敗: {str(e)[:15]}", ""

# --- 5. 介面渲染 ---
init_db()
st.title("日本国內発送用")

# 側邊欄：新增與刪除
with st.sidebar:
    st.header("➕ 新增項目")
    input_id = st.text_input("輸入商品 ID")
    input_url_full = st.text_input("或 貼上完整連結")
    
    if st.button("執行抓取", use_container_width=True, type="primary"):
        final_url = ""
        val = input_id.strip()
        if val:
            if val.startswith('m'): final_url = f"https://jp.mercari.com/item/{val}"
            elif len(val) >= 9: final_url = f"https://auctions.yahoo.co.jp/jp/auction/{val}"
            else: final_url = f"https://jp.mercari.com/shops/product/{val}"
        elif input_url_full:
            final_url = input_url_full.strip()

        if final_url:
            with st.spinner("抓取中..."):
                t, img = get_web_data(final_url)
                if img and "失敗" not in t:
                    with sqlite3.connect('mercari.db') as conn:
                        conn.execute("INSERT INTO items (title, url, img_url, note, price, local_img, local_img2, is_done) VALUES (?,?,?,?,?,?,?,0)",
                                     (t, final_url, img, "備註...", "0", "", ""))
                    st.success("成功！")
                    st.rerun()
                else: st.error(f"失敗: {t}")

    st.divider()
    st.header("⚙️ 系統管理")
    if st.checkbox("開啟管理員操作"):
        if st.button("🗑️ 清空所有項目", use_container_width=True):
            with sqlite3.connect('mercari.db') as conn:
                conn.execute("DELETE FROM items")
            for f in os.listdir(UPLOAD_DIR):
                os.remove(os.path.join(UPLOAD_DIR, f))
            st.rerun()

# 顯示列表
with sqlite3.connect('mercari.db') as conn:
    df = pd.read_sql_query("SELECT * FROM items ORDER BY is_done ASC, id DESC", conn)

for index, row in df.iterrows():
    with st.container(border=True):
        t_col1, t_col2 = st.columns([1, 4])
        with t_col1:
            check = st.checkbox("已發貨", value=(row['is_done'] == 1), key=f"done_{row['id']}")
            if check != (row['is_done'] == 1):
                update_status(row['id'], 1 if check else 0); st.rerun()
        with t_col2:
            if row['is_done'] == 1: st.markdown(":gray[已標記為完成]")

        c1, c2, c3 = st.columns([1.2, 1.2, 2.5])
        
        with c1:
            st.caption("主圖")
            img_show = row['local_img'] if row['local_img'] and os.path.exists(row['local_img']) else row['img_url']
            if img_show: st.image(img_show, use_container_width=True)
            with st.expander("📷 更換"):
                up1 = st.file_uploader("up1", type=['jpg','png'], key=f"up1_{row['id']}")
                if up1:
                    path = os.path.join(UPLOAD_DIR, f"m_{row['id']}.png")
                    with open(path, "wb") as f: f.write(up1.getbuffer())
                    update_db_simple(row['id'], row['title'], row['note'], row['price'], img1=path); st.rerun()

        with c2:
            st.caption("細節圖")
            if row['local_img2'] and os.path.exists(row['local_img2']):
                if st.button(f"🔍 放大圖", key=f"view_{row['id']}", use_container_width=True):
                    show_full_image(row['local_img2'])
            with st.expander("📷 上傳"):
                up2 = st.file_uploader("up2", type=['jpg','png'], key=f"up2_{row['id']}")
                if up2:
                    path = os.path.join(UPLOAD_DIR, f"p_{row['id']}.png")
                    with open(path, "wb") as f: f.write(up2.getbuffer())
                    update_db_simple(row['id'], row['title'], row['note'], row['price'], img2=path); st.rerun()

        with c3:
            new_t = st.text_input("名稱", value=row['title'], key=f"t_{row['id']}")
            p_c, n_c = st.columns([1, 2])
            with p_c: new_p = st.text_input("條碼", value=row['price'], key=f"p_{row['id']}")
            with n_c: new_n = st.text_area("備註", value=row['note'], key=f"n_{row['id']}", height=68)
            
            b1, b2, b3 = st.columns(3)
            with b1:
                if st.button("💾 儲存", key=f"s_{row['id']}", use_container_width=True, type="primary"):
                    update_db_simple(row['id'], new_t, new_n, new_p); st.rerun()
            with b2: st.link_button("🔗 網頁", row['url'], use_container_width=True)
            with b3:
                if st.button("🗑️ 刪除", key=f"del_{row['id']}", use_container_width=True):
                    with sqlite3.connect('mercari.db') as conn:
                        conn.execute("DELETE FROM items WHERE id=?", (row['id'],))
                    st.rerun()
