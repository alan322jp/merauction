import streamlit as st
import os
import sys
import subprocess
import time

# --- 0. 環境強制初始化 (解決 BrowserType.launch 與路徑問題) ---
@st.cache_resource
def ensure_environment_is_ready():
    try:
        # 使用 sys.executable 確保指向 Python 3.13 虛擬環境
        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
        return True
    except Exception as e:
        st.error(f"瀏覽器環境初始化失敗: {e}")
        return False

# 啟動時先跑安裝
if not ensure_environment_is_ready():
    st.stop()

# --- 1. 安全導入套件 (確保安裝完後才 Import) ---
from playwright.sync_api import sync_playwright
from supabase import create_client, Client

# --- 2. 初始化 Supabase ---
try:
    url: str = st.secrets["supabase_url"]
    key: str = st.secrets["supabase_key"]
    supabase: Client = create_client(url, key)
except Exception as e:
    st.error(f"Supabase 連接失敗，請檢查 Secrets: {e}")
    st.stop()

# --- 3. 抓取函數 (修正 NameError 的核心) ---
def get_web_data(target_url):
    with sync_playwright() as p:
        browser = None
        try:
            # 1. 偽裝真人啟動參數
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-blink-features=AutomationControlled", # 隱藏自動化標記
                    "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
                ]
            )
            context = browser.new_context()
            page = context.new_page()
            
            # 2. 延長超時並模擬真人等待
            # 使用 'domcontentloaded' 縮短等待 HTML 的時間，但後續用 sleep 等待 JS
            page.goto(target_url, wait_until="domcontentloaded", timeout=60000)
            
            # 拿到初步標題 (這步你之前已經成功了)
            raw_title = page.title()
            
            # 等待 4 秒讓日本拍賣的動態圖片跑出來
            time.sleep(4) 

            # 3. 多重嘗試抓取標題 (有些網站標題在 h1)
            final_title = raw_title
            h1_selector = page.locator("h1").first
            if h1_selector.count() > 0:
                h1_text = h1_selector.inner_text().strip()
                if h1_text:
                    final_title = h1_text

            # 4. 針對日拍 (Yahoo/Mercari) 的圖片選擇器清單
            img_src = ""
            selectors = [
                "div.ProductImage__image img", # Yahoo Auction
                "img[data-testid='image-0']",   # Mercari
                "figure img",                   # 一般拍賣
                "div.Carousel__item img"        # 其他
            ]
            
            for selector in selectors:
                img_node = page.locator(selector).first
                if img_node.count() > 0:
                    img_src = img_node.get_attribute("src")
                    if img_src: break

            # 5. 回傳結果 (只要有標題，就不報失敗)
            return final_title, img_src

        except Exception as e:
            # 即使失敗，如果已經拿到 raw_title，就回傳它，不要讓 UI 顯示抓取失敗
            if 'raw_title' in locals() and raw_title:
                return raw_title, ""
            return f"連線不穩: {str(e)[:50]}", ""
        finally:
            if browser:
                browser.close()

# --- 4. UI 介面 ---
st.title("🛡️ 拍賣監測助手")

with st.sidebar:
    input_url = st.text_input("輸入商品網址")
    if st.button("開始監測"):
        if input_url:
            with st.spinner("正在解析網頁..."):
                t, img = get_web_data(input_url)
                if "失敗" not in t:
                    supabase.table("items").insert({"title": t, "image_url": img, "url": input_url}).execute()
                    st.success(f"成功加入: {t}")
                else:
                    st.error(t)

# 顯示清單
st.header("監測清單")
try:
    res = supabase.table("items").select("*").execute()
    for item in res.data:
        st.write(f"📍 {item['title']}")
except:
    st.info("目前無資料。")
# --- 1. 連接 Supabase 與後續邏輯 ---
# ... (之後的程式碼)

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
