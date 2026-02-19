import streamlit as st
from playwright.sync_api import sync_playwright
import sqlite3
import pandas as pd
import time
import os

# --- 1. 初始化環境 ---
UPLOAD_DIR = "uploaded_images"
if not os.path.exists(UPLOAD_DIR):
    os.makedirs(UPLOAD_DIR)

st.set_page_config(layout="wide", page_title="Multi-Platform Manager")

# --- 2. 資料庫核心功能 ---
def init_db():
    with sqlite3.connect('mercari.db') as conn:
        # 建立表（包含 is_done）
        conn.execute('''CREATE TABLE IF NOT EXISTS items 
                        (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                         title TEXT, url TEXT, img_url TEXT, 
                         note TEXT, price TEXT, local_img TEXT, local_img2 TEXT,
                         is_done INTEGER DEFAULT 0)''')
        # 額外檢查：如果舊表存在但沒 is_done 欄位，則手動增加
        try:
            conn.execute("ALTER TABLE items ADD COLUMN is_done INTEGER DEFAULT 0")
        except:
            pass # 欄位已存在

def update_db_simple(item_id, title, note, price, img1=None, img2=None):
    with sqlite3.connect('mercari.db') as conn:
        conn.execute("UPDATE items SET title=?, note=?, price=? WHERE id=?", (title, note, price, item_id))
        if img1: conn.execute("UPDATE items SET local_img=? WHERE id=?", (img1, item_id))
        if img2: conn.execute("UPDATE items SET local_img2=? WHERE id=?", (img2, item_id))
        conn.commit()

def update_status(item_id, status):
    """更新完成狀態"""
    with sqlite3.connect('mercari.db') as conn:
        conn.execute("UPDATE items SET is_done=? WHERE id=?", (status, item_id))
        conn.commit()

# --- 3. 彈窗大圖功能 ---
@st.dialog("發貨用")
def show_full_image(img_path):
    if img_path and os.path.exists(img_path):
        st.image(img_path, use_container_width=True)
    else:
        st.warning("⚠️ 此項目尚未上傳圖 2。")

# --- 4. 深度優化爬蟲核心 ---
def get_web_data(url):
    # --- 新增這段：自動下載瀏覽器核心 ---
    import os
    import subprocess
    
    # 確保環境變數路徑正確 (Streamlit Cloud 常用設定)
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = "0" 
    
    # 執行安裝指令
    subprocess.run(["playwright", "install", "chromium"])
    # ----------------------------------

    with sync_playwright() as p:
        # 加入 args 避開 sandbox 限制
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox"]
        )
        # ... 原有代碼 ...
    
def get_web_data(url):
    import os
    import subprocess
    from playwright.sync_api import sync_playwright

    # 1. 強制設定 Playwright 瀏覽器安裝路徑
    # 這確保了 playwright install 的位置與 launch 尋找的位置一致
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = "/home/adminuser/playwright_browsers"

    # 2. 檢查並自動安裝 Chromium (如果不存在才安裝，節省啟動時間)
    if not os.path.exists(os.environ["PLAYWRIGHT_BROWSERS_PATH"]):
        subprocess.run(["python", "-m", "playwright", "install", "chromium"])
        subprocess.run(["python", "-m", "playwright", "install-deps"])

    with sync_playwright() as p:
        try:
            # 3. 啟動瀏覽器：必須加入 args 避開 Linux 權限限制
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox", 
                    "--disable-setuid-sandbox", 
                    "--disable-dev-shm-usage", # 防止記憶體不足
                    "--disable-gpu"
                ]
            )
            
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                locale="ja-JP",
                viewport={'width': 1280, 'height': 800}
            )
            page = context.new_page()
            
            # --- 以下維持你原有的爬蟲邏輯 ---
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
                title = page.locator('h1').first.inner_text().strip()
                img = page.locator('div[data-testid="image-0"] img, img[alt="product-image"]').first.get_attribute('src')
            
            browser.close()
            return title, img

        except Exception as e:
            if 'browser' in locals():
                browser.close()
            return f"抓取失敗: {str(e)[:20]}", ""

# --- 5. 介面渲染 ---
init_db()
st.title("ヤフオク・メルカリ發送平台")

# --- 側邊欄：新增項目 ---
with st.sidebar:
    st.header("➕ 新增項目")
    input_id = st.text_input("輸入商品 ID (m... / Yahoo ID / Shops ID)")
    input_url_full = st.text_input("或 貼上完整連結")
    
    if st.button("執行抓取", use_container_width=True, type="primary"):
        final_url = ""
        if input_id:
            val = input_id.strip()
            if val.startswith('m'):
                final_url = f"https://jp.mercari.com/item/{val}"
            elif (val[0].isalpha() or val[0].isdigit()) and len(val) >= 9:
                final_url = f"https://auctions.yahoo.co.jp/jp/auction/{val}"
            else:
                final_url = f"https://jp.mercari.com/shops/product/{val}"
        elif input_url_full:
            final_url = input_url_full.strip()

        if final_url:
            with st.spinner(f"正在抓取: {final_url}"):
                t, img = get_web_data(final_url)
                if img and "抓取失敗" not in t and t != "未知標題":
                    with sqlite3.connect('mercari.db') as conn:
                        conn.execute("INSERT INTO items (title, url, img_url, note, price, local_img, local_img2, is_done) VALUES (?,?,?,?,?,?,?,0)",
                                     (t, final_url, img, "請輸入備註...", "0", "", ""))
                    st.success("抓取成功！")
                    st.rerun()
                else:
                    st.error(f"抓取失敗。標題: {t}")

# --- 顯示列表 (關鍵排序：未完成在前，已完成在後) ---
with sqlite3.connect('mercari.db') as conn:
    df = pd.read_sql_query("SELECT * FROM items ORDER BY is_done ASC, id DESC", conn)

for index, row in df.iterrows():
    # 根據是否完成來顯示容器，已完成的可以加一點提示
    with st.container(border=True):
        # 頂部狀態列：Checkbox
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
            st.caption("主圖 (Image 1)")
            img1_display = row['local_img'] if row['local_img'] and os.path.exists(row['local_img']) else row['img_url']
            if img1_display:
                st.image(img1_display, use_container_width=True)
            
            up1 = st.file_uploader("更換主圖", type=['jpg','png'], key=f"up1_{row['id']}")
            if up1:
                p1 = os.path.join(UPLOAD_DIR, f"m_{row['id']}.png")
                with open(p1, "wb") as f: f.write(up1.getbuffer())
                update_db_simple(row['id'], row['title'], row['note'], row['price'], img1=p1)
                st.rerun()

        with col_img2:
            st.caption("細節圖 (Image 2)")
            if row['local_img2'] and os.path.exists(row['local_img2']):
                if st.button(f"🔍 點擊發貨", key=f"view_{row['id']}", use_container_width=True):
                    show_full_image(row['local_img2'])
            else:
                st.info("尚未上傳圖 2")
            
            up2 = st.file_uploader("上傳圖 2", type=['jpg','png'], key=f"up2_{row['id']}")
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
                new_note = st.text_area("備註", value=row['note'], key=f"n_{row['id']}", height=100)
            
            b1, b2, b3 = st.columns(3)
            with b1:
                if st.button("💾 儲存修改", key=f"save_{row['id']}", use_container_width=True, type="primary"):
                    update_db_simple(row['id'], new_title, new_note, new_price)
                    for k in [f"t_{row['id']}", f"p_{row['id']}", f"n_{row['id']}"]:
                        if k in st.session_state: del st.session_state[k]
                    st.rerun()
            with b2:
                st.link_button("🔗 原始網頁", row['url'], use_container_width=True)
            with b3:
                if st.button("🗑️ 刪除", key=f"del_{row['id']}", use_container_width=True):
                    with sqlite3.connect('mercari.db') as conn:
                        conn.execute("DELETE FROM items WHERE id=?", (row['id'],))
                    st.rerun()
