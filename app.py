import streamlit as st
import os
import sys
import subprocess
import time

# --- 0. 核心環境初始化 (必須放在最前面) ---
@st.cache_resource
def init_browser_env():
    """確保 Playwright 瀏覽器在雲端環境正確安裝"""
    try:
        # 使用 sys.executable 確保指向當前的 Python 虛擬環境
        # 這能解決 CalledProcessError 與 status 1 的問題
        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
        return True
    except Exception as e:
        st.error(f"環境初始化失敗: {e}")
        return False

# 執行初始化
if not init_browser_env():
    st.stop()

# --- 1. 導入必要套件 (初始化成功後再導入) ---
try:
    from playwright.sync_api import sync_playwright
    from supabase import create_client, Client
except ImportError:
    st.error("必要的套件 (playwright/supabase) 尚未安裝，請檢查 requirements.txt")
    st.stop()

# --- 2. 初始化 Supabase ---
try:
    url: str = st.secrets["supabase_url"]
    key: str = st.secrets["supabase_key"]
    supabase: Client = create_client(url, key)
except Exception as e:
    st.error(f"Supabase 連接失敗，請檢查 Secrets 設定: {e}")
    st.stop()

# --- 3. 抓取函數 (極致穩定版) ---
def get_web_data(target_url):
    """使用 Playwright 抓取資料"""
    # 這裡現在能正確調用 sync_playwright 了
    with sync_playwright() as p:
        browser = None
        try:
            # 針對 Linux 雲端容器的啟動參數
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-gpu",
                    "--disable-dev-shm-usage",
                    "--single-process"
                ]
            )
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            )
            page = context.new_page()
            
            # 設定超時並導向網址
            page.goto(target_url, wait_until="domcontentloaded", timeout=45000)
            time.sleep(3) # 給予 JS 渲染時間

            # 抓取邏輯 (以抓取標題為例)
            title = page.title()
            
            # 嘗試抓取特定圖片 (根據你的需求調整選擇器)
            img_src = ""
            img_element = page.locator("img").first
            if img_element.count() > 0:
                img_src = img_element.get_attribute("src")

            return title, img_src

        except Exception as e:
            return f"抓取失敗: {str(e)}", ""
        finally:
            if browser:
                browser.close()

# --- 4. Streamlit UI 介面 ---
st.set_page_config(page_title="拍賣監測助手", page_icon="🛡️")
st.title("🛡️ 拍賣平台雲端自動化")

with st.sidebar:
    st.header("新增監測項目")
    input_url = st.text_input("輸入商品網址")
    if st.button("開始抓取並儲存"):
        if input_url:
            with st.spinner("正在爬取網頁資訊..."):
                res_title, res_img = get_web_data(input_url)
                if "失敗" not in res_title:
                    # 儲存到 Supabase
                    data = {"title": res_title, "image_url": res_img, "url": input_url}
                    supabase.table("items").insert(data).execute()
                    st.success(f"已成功加入: {res_title}")
                else:
                    st.error(res_title)

# 主畫面顯示雲端資料
st.header("目前監測中的清單")
try:
    response = supabase.table("items").select("*").execute()
    items = response.data
    if items:
        for item in items:
            with st.expander(f"{item.get('title', '未知商品')}"):
                if item.get('image_url'):
                    st.image(item['image_url'], width=200)
                st.write(f"網址: {item['url']}")
    else:
        st.info("目前雲端沒有資料，請從側邊欄新增。")
except Exception as e:
    st.warning(f"讀取資料表失敗 (請確認資料表 items 是否已建立): {e}")
