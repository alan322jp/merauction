import streamlit as st
from playwright.sync_api import sync_playwright
import sqlite3
import pandas as pd
import time
import os
import sys
import subprocess

# --- 0. 環境修復 (確保 Streamlit Cloud 能跑 Playwright) ---
def ensure_playwright_installed():
    try:
        import playwright
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "playwright"])
    subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"])

ensure_playwright_installed()

# --- 1. 初始化環境 ---
UPLOAD_DIR = "uploaded_images"
if not os.path.exists(UPLOAD_DIR):
    os.makedirs(UPLOAD_DIR)

st.set_page_config(layout="wide", page_title="ヤフオク・メルカリ發送平台")

# CSS 注入：縮小上傳組件並隱藏標籤文字 (回應你的縮小需求)
# --- CSS 注入：優化手機與電腦版面 ---
st.markdown("""
    <style>
    /* 1. 限制電腦版最大寬度，並讓內容居中 */
    .block-container {
        max-width: 1000px !important;
        padding-top: 2rem !important;
        padding-bottom: 2rem !important;
    }

    /* 2. 通用字體縮小 */
    html, body, [class*="css"] {
        font-size: 14px !important;
    }

    /* 3. 縮小上傳組件 (隱藏標籤並壓縮) */
    .stFileUploader label { display: none; }
    .stFileUploader section { 
        padding: 0px 5px !important; 
        min-height: 35px !important; 
    }

    /* 4. 針對手機尺寸 (螢幕寬度小於 768px) 的特殊調整 */
    @media (max-width: 768px) {
        .block-container {
            padding-left: 0.5rem !important;
            padding-right: 0.5rem !important;
        }
        /* 讓文字更小以適應窄螢幕 */
        p, span, label, input, textarea, button {
            font-size: 12px !important;
        }
        /* 縮減容器內邊距 */
        div[data-testid="stVerticalBlock"] {
            gap: 0.5rem !important;
        }
        /* 讓按鈕高度降低 */
        .stButton button {
            padding: 0px 10px !important;
            height: 30px !important;
        }
    }

    /* 5. 隱藏 Expander 的框線讓視覺更乾淨 */
    div[data-testid="stExpander"] { 
        border: none !important; 
        box-shadow: none !important; 
        background-color: transparent !important;
    }
    .streamlit-expanderHeader {
        padding: 0px !important;
        font-size: 12px !important;
        color: #666;
    }
    /* 標題字體大小設定為 20px */
    h1 {
        font-size: 20px !important;
        font-weight: 600 !important;
    }
    </style>
    """, unsafe_allow_html=True)

# --- 2. 資料庫核心功能 (保留原始邏輯) ---
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

# --- 3. 彈窗大圖功能 ---
@st.dialog("發貨用")
def show_full_image(img_path):
    if img_path and os.path.exists(img_path):
        st.image(img_path, width='stretch')
    else:
        st.warning("⚠️ 此項目尚未上傳圖 2。")

# --- 4. 爬蟲核心 (整合 Playwright 與相容性參數) ---
def get_web_data(url):
    with sync_playwright() as p:
        # 加入 args 以確保在 Linux 容器中穩定執行
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-gpu"])
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            locale="ja-JP",
            viewport={'width': 1280, 'height': 800}
        )
        page = context.new_page()
        try:
            page.goto(url, wait_until="load", timeout=30000)
            time.sleep(3) 
            
            title = "未知標題"
            img = ""

            if "yahoo.co.jp" in url:
                title_selectors = ['h1.Title__text', 'h1.ProductTitle__text', '.ProductTitle__title', 'h1']
                for s in title_selectors:
                    loc = page.locator(s).first
                    if loc.count() > 0:
                        t_text = loc.inner_text().strip()
                        if t_text: title = t_text; break
                
                page.evaluate("window.scrollTo(0, 400)")
                time.sleep(1)
                img_selectors = ['div.ProductImage__image img', '.ProductImage__body img', '.Image__img', 'div[data-index="0"] img']
                for s in img_selectors:
                    loc = page.locator(s).first
                    if loc.count() > 0:
                        i_src = loc.get_attribute('src')
                        if i_src: img = i_src; break
            else:
                # 針對 Mercari / Shops 的標題抓取
                title = page.locator('h1').first.inner_text().strip()
                # 針對 Mercari / Shops 的圖片抓取
                img = page.locator('div[data-testid="image-0"] img, img[alt="product-image"]').first.get_attribute('src')
                
            browser.close()
            return title, img
        except Exception as e:
            if 'browser' in locals(): browser.close()
            return f"抓取失敗: {str(e)[:15]}", ""

# --- 5. 介面渲染 ---
init_db()
st.title("ヤフオク・メルカリ發送平台")

# --- 側邊欄：新增與全域管理 ---
# --- 側邊欄：新增項目 (改為 Select 模式) ---
with st.sidebar:
    st.header("➕ 新增項目")
    
    # 1. 選擇平台類型
    platform = st.selectbox(
        "選擇平台類型",
        ["Mercari 一般", "Yahoo 拍賣", "Mercari Shops"],
        index=0
    )
    
    # 2. 輸入純 ID
    input_id = st.text_input("輸入商品 ID", placeholder="例如: m45936918194")
    
    # 3. 備用：直接貼連結 (保留此功能以防萬一)
    input_url_full = st.text_input("或直接貼上完整連結", placeholder="https://...")
    
    if st.button("執行抓取", width='stretch', type="primary"):
        final_url = ""
        val = input_id.strip()
        
        if val:
            # 根據選擇的平台組合網址
            if platform == "Mercari 一般":
                # 自動補全 m 字頭
                item_id = val if val.startswith('m') else f"m{val}"
                final_url = f"https://jp.mercari.com/item/{item_id}"
            
            elif platform == "Yahoo 拍賣":
                # Yahoo ID 通常是字母數字組合，例如 r1220130745
                final_url = f"https://auctions.yahoo.co.jp/jp/auction/{val}"
            
            elif platform == "Mercari Shops":
                # Shops ID 通常是一串亂碼，例如 2JHuzbFCcgRv8rLyUQhNM8
                final_url = f"https://jp.mercari.com/shops/product/{val}"
        
        elif input_url_full:
            final_url = input_url_full.strip()

        if final_url:
            with st.spinner(f"正在從 {platform} 抓取..."):
                t, img = get_web_data(final_url)
                if img and "抓取失敗" not in t and t != "未知標題":
                    with sqlite3.connect('mercari.db') as conn:
                        conn.execute("INSERT INTO items (title, url, img_url, note, price, local_img, local_img2, is_done) VALUES (?,?,?,?,?,?,?,0)",
                                     (t, final_url, img, "請輸入備註...", "0", "", ""))
                    st.success(f"成功抓取 {platform} 商品！")
                    st.rerun()
                else:
                    st.error(f"抓取失敗。標題: {t}")

    st.divider()
    # ... (後續的系統管理按鈕)

    st.divider()
    st.header("⚙️ 系統管理")
    if st.checkbox("開啟危險操作"):
        if st.button("🗑️ 清空所有項目", width='stretch'):
            with sqlite3.connect('mercari.db') as conn:
                conn.execute("DELETE FROM items")
            for f in os.listdir(UPLOAD_DIR):
                os.remove(os.path.join(UPLOAD_DIR, f))
            st.rerun()

# --- 顯示列表 (關鍵排序：未完成在前，已完成在後) ---
with sqlite3.connect('mercari.db') as conn:
    df = pd.read_sql_query("SELECT * FROM items ORDER BY is_done ASC, id DESC", conn)

for index, row in df.iterrows():
    with st.container(border=True):
        t_col1, t_col2 = st.columns([1, 4])
        with t_col1:
            is_done_val = (row['is_done'] == 1)
            check = st.checkbox("已完成", value=is_done_val, key=f"done_{row['id']}")
            if check != is_done_val:
                update_status(row['id'], 1 if check else 0)
                st.rerun()
        with t_col2:
            if row['is_done'] == 1:
                st.markdown(":gray[這筆資料已標記為完成]")

        col_img1, col_img2, col_info = st.columns([1.2, 1.2, 2.5])
        
        with col_img1:
            st.caption("主圖")
            img1_display = row['local_img'] if row['local_img'] and os.path.exists(row['local_img']) else row['img_url']
            if img1_display:
                st.image(img1_display, width='stretch')
            
            # 使用 Expander 縮小上傳空間
            with st.expander("📷 更換"):
                up1 = st.file_uploader("up1", type=['jpg','png'], key=f"up1_{row['id']}")
                if up1:
                    p1 = os.path.join(UPLOAD_DIR, f"m_{row['id']}.png")
                    with open(p1, "wb") as f: f.write(up1.getbuffer())
                    update_db_simple(row['id'], row['title'], row['note'], row['price'], img1=p1)
                    st.rerun()

        with col_img2:
            st.caption("細節圖")
            if row['local_img2'] and os.path.exists(row['local_img2']):
                if st.button(f"🔍 點擊發貨", key=f"view_{row['id']}", width='stretch'):
                    show_full_image(row['local_img2'])
            else:
                st.info("無圖 2")
            
            with st.expander("📷 上傳"):
                up2 = st.file_uploader("up2", type=['jpg','png'], key=f"up2_{row['id']}")
                if up2:
                    p2 = os.path.join(UPLOAD_DIR, f"p_{row['id']}.png")
                    with open(p2, "wb") as f: f.write(up2.getbuffer())
                    update_db_simple(row['id'], row['title'], row['note'], row['price'], img2=p2)
                    st.rerun()

        with col_info:
            new_title = st.text_input("商品名稱", value=row['title'], key=f"t_{row['id']}")
            p_col, n_col = st.columns([1, 2])
            with p_col:
                new_price = st.text_input("Bar Code", value=row['price'], key=f"p_{row['id']}")
            with n_col:
                new_note = st.text_area("備註", value=row['note'], key=f"n_{row['id']}", height=68)
            
            b1, b2, b3 = st.columns(3)
            with b1:
                if st.button("💾 儲存", key=f"save_{row['id']}", width='stretch', type="primary"):
                    update_db_simple(row['id'], new_title, new_note, new_price)
                    st.rerun()
            with b2:
                st.link_button("🔗 網頁", row['url'], width='stretch')
            with b3:
                if st.button("🗑️ 刪除", key=f"del_{row['id']}", width='stretch'):
                    with sqlite3.connect('mercari.db') as conn:
                        conn.execute("DELETE FROM items WHERE id=?", (row['id'],))
                    st.rerun()
