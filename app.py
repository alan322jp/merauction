import streamlit as st
import sqlite3
import pandas as pd
import time
import os
import sys
import subprocess

# --- 0. 環境修復 ---
def ensure_playwright_installed():
    try:
        import playwright
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "playwright"])
    subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"])

ensure_playwright_installed()
from playwright.sync_api import sync_playwright

# --- 1. 初始化與 CSS ---
UPLOAD_DIR = "uploaded_images"
if not os.path.exists(UPLOAD_DIR):
    os.makedirs(UPLOAD_DIR)

st.set_page_config(layout="wide", page_title="拍賣發送平台")

st.markdown("""
    <style>
    .stFileUploader label { display: none; }
    .stFileUploader section { padding: 0px 5px !important; min-height: 40px !important; }
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

def update_db_simple(item_id, title, note, price, img1=None, img2=None):
    with sqlite3.connect('mercari.db') as conn:
        conn.execute("UPDATE items SET title=?, note=?, price=? WHERE id=?", (title, note, price, item_id))
        if img1: conn.execute("UPDATE items SET local_img=? WHERE id=?", (img1, item_id))
        if img2: conn.execute("UPDATE items SET local_img2=? WHERE id=?", (img2, item_id))

def update_status(item_id, status):
    with sqlite3.connect('mercari.db') as conn:
        conn.execute("UPDATE items SET is_done=? WHERE id=?", (status, item_id))

@st.dialog("發貨細節圖")
def show_full_image(img_path):
    st.image(img_path, width='stretch')

# --- 4. 針對 Shops 優化的強化版爬蟲 ---
def get_web_data(url):
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-gpu"])
            # 模擬真實瀏覽器行為，這對 Mercari Shops 至關重要
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={'width': 1280, 'height': 800}
            )
            page = context.new_page()
            
            # 針對 Shops 使用更長的等待時間與 networkidle
            page.goto(url, wait_until="networkidle", timeout=60000)
            time.sleep(4) # 給予額外的渲染時間
            
            title = "未知標題"
            img = ""

            # 抓取標題：加入 Shops 特有的屬性標籤
            t_selectors = [
                'h1[data-testid="product-name"]', 
                'h1[class*="ProductDetail"]',
                'h1.Title__text', 
                '.ProductTitle__title',
                'p[class*="ProductNameText"]', # Shops 常見標籤
                'h1'
            ]
            for s in t_selectors:
                loc = page.locator(s).first
                if loc.count() > 0:
                    t_text = loc.inner_text().strip()
                    if t_text: title = t_text; break

            # 抓取圖片：全面覆蓋 Yahoo / Shops / Mercari
            img_selectors = [
                'div[data-testid="image-0"] img',        # Mercari / Shops
                'img[class*="ProductImage"]',           # Shops 專屬
                'div.ProductImage__image img',          # Yahoo
                'li.ProductImage__imagesItem img',      # Yahoo 備用
                'img[src*="auc-pctr.c.yimg.jp"]',       # Yahoo 伺服器
                'img[alt="product-image"]'              # 通用備用
            ]
            for s in img_selectors:
                loc = page.locator(s).first
                if loc.count() > 0:
                    i_src = loc.get_attribute('src')
                    if i_src: img = i_src; break
                
            browser.close()
            
            # 防呆機制：只要抓到標題就算成功
            if title != "未知標題" and not img:
                img = "https://placehold.jp/24/cccccc/ffffff/200x200.png?text=圖片載入失敗_可手動上傳"
            
            return title, img
        except Exception as e:
            if 'browser' in locals(): browser.close()
            return f"連線超時: {str(e)[:15]}", ""

# --- 5. 介面渲染 ---
init_db()
st.title("🛡️ 拍賣發送平台")

with st.sidebar:
    st.header("➕ 新增項目")
    input_id = st.text_input("輸入商品 ID (m... 或 Yahoo ID)")
    input_url_full = st.text_input("或 貼上完整連結")
    
    if st.button("執行抓取", width='stretch', type="primary"):
        final_url = ""
        val = input_id.strip()
        if val:
            if val.startswith('m'): 
                # 自動嘗試轉換 Shops 連結格式
                if len(val) > 15: # Shops ID 通常較長
                    final_url = f"https://mercari-shops.com/products/{val}"
                else:
                    final_url = f"https://jp.mercari.com/item/{val}"
            elif len(val) >= 9: 
                final_url = f"https://auctions.yahoo.co.jp/jp/auction/{val}"
        elif input_url_full:
            final_url = input_url_full.strip()

        if final_url:
            with st.spinner("深度掃描 Shops / Yahoo 頁面中..."):
                t, img = get_web_data(final_url)
                # 只要抓到非「未知」的標題就允許存檔
                if "未知標題" not in t and "連線超時" not in t:
                    with sqlite3.connect('mercari.db') as conn:
                        conn.execute("INSERT INTO items (title, url, img_url, note, price, local_img, local_img2, is_done) VALUES (?,?,?,?,?,?,?,0)",
                                     (t, final_url, img, "備註...", "0", "", ""))
                    st.success("成功！項目已建立。")
                    st.rerun()
                else: st.error(f"抓取失敗: {t}")

    st.divider()
    if st.checkbox("開啟危險操作"):
        if st.button("🗑️ 清空所有項目", width='stretch'):
            with sqlite3.connect('mercari.db') as conn:
                conn.execute("DELETE FROM items")
            st.rerun()

# --- 列表顯示 ---
with sqlite3.connect('mercari.db') as conn:
    df = pd.read_sql_query("SELECT * FROM items ORDER BY is_done ASC, id DESC", conn)

for index, row in df.iterrows():
    with st.container(border=True):
        t_col1, t_col2 = st.columns([1, 4])
        with t_col1:
            if st.checkbox("完成", value=(row['is_done'] == 1), key=f"d_{row['id']}"):
                update_status(row['id'], 1); st.rerun()
            elif row['is_done'] == 1:
                update_status(row['id'], 0); st.rerun()
        with t_col2:
            st.write(f"**{row['title']}**")

        c1, c2, c3 = st.columns([1.2, 1.2, 2.5])
        with c1:
            img_src = row['local_img'] if row['local_img'] and os.path.exists(row['local_img']) else row['img_url']
            st.image(img_src, width='stretch')
            with st.expander("📷 更換圖 1"):
                up1 = st.file_uploader("u1", type=['jpg','png'], key=f"u1_{row['id']}")
                if up1:
                    path = os.path.join(UPLOAD_DIR, f"m_{row['id']}.png")
                    with open(path, "wb") as f: f.write(up1.getbuffer())
                    update_db_simple(row['id'], row['title'], row['note'], row['price'], img1=path); st.rerun()
        
        with c2:
            if row['local_img2'] and os.path.exists(row['local_img2']):
                if st.button("🔍 放大圖 2", key=f"v_{row['id']}", width='stretch'):
                    show_full_image(row['local_img2'])
            else: st.info("無圖 2")
            with st.expander("📷 上傳圖 2"):
                up2 = st.file_uploader("u2", type=['jpg','png'], key=f"u2_{row['id']}")
                if up2:
                    path = os.path.join(UPLOAD_DIR, f"p_{row['id']}.png")
                    with open(path, "wb") as f: f.write(up2.getbuffer())
                    update_db_simple(row['id'], row['title'], row['note'], row['price'], img2=path); st.rerun()

        with c3:
            # 儲存、網頁、刪除按鈕
            sc1, sc2, sc3 = st.columns(3)
            with sc1:
                if st.button("💾 儲存", key=f"s_{row['id']}", width='stretch', type="primary"):
                    # 此處可加入修改標題/備註的邏輯
                    st.rerun()
            with sc2: st.link_button("🔗 網頁", row['url'], width='stretch')
            with sc3:
                if st.button("🗑️ 刪除", key=f"del_{row['id']}", width='stretch'):
                    with sqlite3.connect('mercari.db') as conn:
                        conn.execute("DELETE FROM items WHERE id=?", (row['id'],))
                    st.rerun()
