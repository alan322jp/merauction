import streamlit as st
from supabase import create_client, Client
from playwright.sync_api import sync_playwright
import time
import os
import sys
import subprocess

# --- 0. 環境強制修復 ---
# --- 0. 環境檢查 (終極修復路徑版) ---
# --- 0. 環境檢查 (本地路徑強制安裝版) ---
def ensure_playwright_installed():
    # 1. 強制讓 Playwright 將瀏覽器安裝在當前 App 目錄下的一個資料夾內
    # 這樣可以避免 /home/appuser/.cache 的權限問題
    local_playwright_path = os.path.join(os.getcwd(), "playwright_browsers")
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = local_playwright_path
    
    # 2. 檢查是否已經下載過
    if not os.path.exists(local_playwright_path):
        with st.spinner("正在將瀏覽器安裝至 App 本地目錄 (預計 1 分鐘)..."):
            try:
                # 執行安裝，不加 sudo，直接指定 chromium
                subprocess.run([
                    sys.executable, "-m", "playwright", "install", "chromium"
                ], env=os.environ, check=True)
                st.success("瀏覽器安裝完成！")
            except subprocess.CalledProcessError as e:
                st.error(f"安裝失敗，狀態碼: {e.returncode}")
                # 嘗試另一種安裝方式作為備援
                st.info("嘗試備援安裝模式...")
                subprocess.run(["playwright", "install", "chromium"], env=os.environ)

ensure_playwright_installed()

# --- 1. 連接 Supabase (請確保 Secrets 已填寫) ---
url: str = st.secrets["supabase_url"]
key: str = st.secrets["supabase_key"]
supabase: Client = create_client(url, key)

# --- 2. 抓取函數 (極致相容模式) ---
def get_web_data(url):
    with sync_playwright() as p:
        browser = None
        try:
            # 這是針對 Streamlit Cloud 的終極啟動參數
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--no-zygote",
                    "--single-process",  # 在小內存環境極端重要
                ]
            )
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            )
            page = context.new_page()
            
            # 針對 Shops 加強載入邏輯
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            time.sleep(5) # 額外給予 JavaScript 渲染時間

            # 抓取標題與圖片
            title = page.title() # 備用方案：先抓網頁 Title
            h1 = page.locator("h1").first
            if h1.count() > 0:
                title = h1.inner_text().strip()
            
            img = ""
            # 優先找主要商品圖
            img_loc = page.locator('img[alt="product-image"], div[data-testid="image-0"] img, .ProductImage__image img').first
            if img_loc.count() > 0:
                img = img_loc.get_attribute("src")

            return title, img

        except Exception as e:
            return f"瀏覽器啟動失敗: {str(e)}", ""
        finally:
            if browser:
                browser.close()

# ... 這裡接你之前的介面渲染程式碼 ...
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
