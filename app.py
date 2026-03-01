import streamlit as st
from supabase import create_client, Client
from playwright.sync_api import sync_playwright
import pandas as pd
import time
import os
import sys
import subprocess

# --- 0. 環境檢查 ---
def ensure_playwright_installed():
    try:
        # 檢查 playwright 是否已安裝
        import playwright
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "playwright"])
    
    # 這是關鍵：安裝 chromium 瀏覽器本體
    # 加上 --with-deps 確保 Linux 系統缺少的依賴庫也會被補齊
    subprocess.run(["playwright", "install", "chromium", "--with-deps"])

ensure_playwright_installed()

# --- 1. 初始化 Supabase 連接 ---
# 請確保已在 Streamlit Secrets 設定 supabase_url 與 supabase_key
url: str = st.secrets["supabase_url"]
key: str = st.secrets["supabase_key"]
supabase: Client = create_client(url, key)

# --- 2. CSS 注入：20px 標題與手機適配 ---
st.set_page_config(layout="wide", page_title="ヤフオク・メルカリ發送平台")

st.markdown("""
    <style>
    /* 全域限寬與居中 */
    .block-container {
        max-width: 1000px !important;
        padding-top: 1.5rem !important;
    }

    /* 標題設定：20px */
    h1 {
        font-size: 20px !important;
        font-weight: 600 !important;
        color: #31333F;
    }

    /* 字體微調與縮小上傳組件 */
    html, body, [class*="css"] { font-size: 14px !important; }
    .stFileUploader label { display: none; }
    .stFileUploader section { padding: 0px 5px !important; min-height: 35px !important; }

    /* 手機版適配 (寬度小於 768px) */
    @media (max-width: 768px) {
        .block-container { padding-left: 0.5rem !important; padding-right: 0.5rem !important; }
        p, span, label, input, textarea, button { font-size: 12px !important; }
        div[data-testid="stVerticalBlock"] { gap: 0.4rem !important; }
        .stButton button { height: 32px !important; padding: 0px !important; }
    }

    /* 乾淨的 Expander 樣式 */
    div[data-testid="stExpander"] { border: none !important; box-shadow: none !important; }
    .streamlit-expanderHeader { padding: 0px !important; font-size: 12px !important; color: #666; }
    </style>
    """, unsafe_allow_html=True)

# --- 3. 核心功能函數 ---
def upload_to_storage(file, file_name):
    """將圖片上傳至 Supabase Storage Bucket"""
    bucket_name = "product_images" # 請確保 Supabase 已建立此 Public Bucket
    supabase.storage.from_(bucket_name).upload(file_name, file.getvalue(), {"content-type": file.type})
    return supabase.storage.from_(bucket_name).get_public_url(file_name)

def get_web_data(url):
    """強化版網頁抓取"""
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-gpu"])
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                locale="ja-JP"
            )
            page = context.new_page()
            
            # 針對 Shops 或普通頁面設定等待
            page.goto(url, wait_until="load", timeout=35000)
            time.sleep(3) 

            title = "未知標題"
            img = ""

            # 標題選擇器 (相容各平台)
            t_selectors = ['h1[data-testid="product-name"]', 'h1.Title__text', 'h1.ProductTitle__text', '.ProductTitle__title', 'h1']
            for s in t_selectors:
                loc = page.locator(s).first
                if loc.count() > 0:
                    t_text = loc.inner_text().strip()
                    if t_text: title = t_text; break

            # 圖片選擇器 (相容各平台)
            i_selectors = ['div[data-testid="image-0"] img', 'div.ProductImage__image img', 'img[alt="product-image"]', 'div[data-index="0"] img']
            for s in i_selectors:
                loc = page.locator(s).first
                if loc.count() > 0:
                    i_src = loc.get_attribute('src')
                    if i_src: img = i_src; break

            browser.close()
            return title, img
        except Exception as e:
            if 'browser' in locals(): browser.close()
            return f"抓取失敗: {str(e)[:15]}", ""

# --- 4. 主介面：側邊欄 ---
st.title("ヤフオク・メルカリ發送平台")

with st.sidebar:
    st.header("➕ 新增項目")
    platform = st.selectbox("來源平台", ["Mercari 一般", "Yahoo 拍賣", "Mercari Shops"])
    input_id = st.text_input("輸入商品 ID", placeholder="例如: m45936918194")
    
    if st.button("執行抓取", width='stretch', type="primary"):
        val = input_id.strip()
        final_url = ""
        if val:
            if platform == "Mercari 一般": final_url = f"https://jp.mercari.com/item/{val if val.startswith('m') else 'm'+val}"
            elif platform == "Yahoo 拍賣": final_url = f"https://auctions.yahoo.co.jp/jp/auction/{val}"
            elif platform == "Mercari Shops": final_url = f"https://jp.mercari.com/shops/product/{val}"
        
        if final_url:
            with st.spinner("雲端同步中..."):
                t, img = get_web_data(final_url)
                if img and "失敗" not in t:
                    supabase.table("items").insert({
                        "title": t, "url": final_url, "img_url": img,
                        "note": "請輸入備註...", "price": "0", "is_done": False
                    }).execute()
                    st.success("已成功存入雲端！")
                    st.rerun()
                else: st.error(f"抓取失敗: {t}")

    st.divider()
    if st.checkbox("開啟系統管理"):
        if st.button("🗑️ 清空雲端所有項目", width='stretch'):
            supabase.table("items").delete().neq("id", 0).execute()
            st.rerun()

# --- 5. 數據加載與清單渲染 ---
try:
    # 排序邏輯：未完成在前，ID 倒序
    res = supabase.table("items").select("*").order("is_done", desc=False).order("id", desc=True).execute()
    items = res.data

    if not items:
        st.info("目前雲端沒有資料，請從側邊欄新增。")

    for item in items:
        with st.container(border=True):
            # 狀態行
            t_col1, t_col2 = st.columns([1, 6])
            with t_col1:
                done = st.checkbox("完", value=item['is_done'], key=f"c_{item['id']}")
                if done != item['is_done']:
                    supabase.table("items").update({"is_done": done}).eq("id", item['id']).execute()
                    st.rerun()
            with t_col2:
                st.write(f"**{item['title']}**" if not item['is_done'] else f":gray[{item['title']}]")

            # 圖片與內容行
            col_img1, col_img2, col_info = st.columns([1.2, 1.2, 2.5])
            
            with col_img1:
                st.caption("主圖")
                st.image(item['img_url'] if item['img_url'] else "https://via.placeholder.com/150", width='stretch')
            
            with col_img2:
                st.caption("細節圖")
                if item.get('local_img_url'):
                    if st.button("🔍 發貨大圖", key=f"v_{item['id']}", width='stretch'):
                        st.image(item['local_img_url'])
                else:
                    st.caption("無圖 2")
                
                with st.expander("📷 上傳"):
                    up = st.file_uploader("Upload", key=f"u_{item['id']}")
                    if up:
                        with st.spinner("圖片上傳雲端..."):
                            f_name = f"detail_{item['id']}_{int(time.time())}.png"
                            p_url = upload_to_storage(up, f_name)
                            supabase.table("items").update({"local_img_url": p_url}).eq("id", item['id']).execute()
                            st.rerun()

            with col_info:
                n_title = st.text_input("名稱", value=item['title'], key=f"t_{item['id']}")
                n_price = st.text_input("Bar Code", value=item['price'], key=f"p_{item['id']}")
                n_note = st.text_area("備註", value=item['note'], key=f"n_{item['id']}", height=68)
                
                b1, b2, b3 = st.columns(3)
                with b1:
                    if st.button("💾 儲存", key=f"s_{item['id']}", width='stretch', type="primary"):
                        supabase.table("items").update({"title": n_title, "note": n_note, "price": n_price}).eq("id", item['id']).execute()
                        st.toast("雲端已更新")
                with b2: st.link_button("🔗 網頁", item['url'], width='stretch')
                with b3:
                    if st.button("🗑️ 刪除", key=f"del_{item['id']}", width='stretch'):
                        supabase.table("items").delete().eq("id", item['id']).execute()
                        st.rerun()
except Exception as e:
    st.warning("正在連線至雲端資料庫...")

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
