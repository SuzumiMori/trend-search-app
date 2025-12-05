import streamlit as st
import pandas as pd
import time
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, ElementClickInterceptedException

# ページの設定
st.set_page_config(page_title="イベント検索（自動展開）", page_icon="🖱️", layout="wide")

st.title("🖱️ イベントリスト「自動展開」抽出アプリ")
st.markdown("""
「もっと見る」ボタンを自動で連打し、隠れている記事を全て展開してから情報を取得します。
※Seleniumを使用するため、処理には時間がかかります。
""")

# --- Selenium設定関数 ---
def get_driver():
    """Streamlit Cloud等で動作するためのヘッドレスドライバー設定"""
    options = Options()
    options.add_argument("--headless")  # 画面を表示しない
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    
    # ローカル環境とクラウド環境でドライバの呼び出し方が異なる場合の吸収
    driver = webdriver.Chrome(options=options)
    return driver

# --- スクレイピング実行関数 ---
def scrape_with_selenium(url, max_clicks=30):
    driver = get_driver()
    extracted_data = []
    status_log = [] # ログ用

    try:
        driver.get(url)
        wait = WebDriverWait(driver, 10)
        
        # --- 1. 「もっと見る」連打パート ---
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        for i in range(max_clicks):
            status_text.text(f"読み込み中... ({i+1}/{max_clicks} 回目クリック)")
            progress_bar.progress((i + 1) / max_clicks)
            
            try:
                # ボタンを探す (クラス名は前回の議論に基づく)
                more_button = wait.until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, "a.js-list-article-more-button"))
                )
                
                # スクロールしてクリック
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", more_button)
                time.sleep(0.5) 
                more_button.click()
                
                # 読み込み待機 (サーバー負荷軽減のため少し待つ)
                time.sleep(2)
                
            except TimeoutException:
                status_log.append("これ以上「もっと見る」ボタンが見つかりません。全件表示された可能性があります。")
                break
            except Exception as e:
                status_log.append(f"クリック中にエラー発生: {str(e)}")
                # リカバリ（少しスクロール）
                driver.execute_script("window.scrollBy(0, -100);")
                time.sleep(1)
                continue
        
        progress_bar.empty()
        status_text.text("ページの展開完了。データ解析中...")

        # --- 2. HTML解析パート ---
        soup = BeautifulSoup(driver.page_source, "html.parser")
        
        # 記事ブロックを取得 (前回のクラス名を使用)
        articles = soup.select("li.list-article__item")
        if not articles:
            articles = soup.select("div.list-article__item")
            
        for article in articles:
            try:
                # タイトル
                title_tag = article.find("div", class_="list-article__title")
                if not title_tag: title_tag = article.find(["h3", "h4"])
                title = title_tag.get_text(strip=True) if title_tag else "不明"

                # URL
                link_tag = article.find("a")
                link_url = link_tag.get("href") if link_tag else ""
                if link_url and not link_url.startswith("http"):
                    # 必要に応じてドメインを結合 (簡易実装)
                    # link_url = "https://example.com" + link_url 
                    pass

                # 日付
                date_tag = article.find("div", class_="list-article__date")
                date_text = date_tag.get_text(strip=True) if date_tag else ""

                # 場所
                place_tag = article.find("div", class_="list-article__place")
                place_text = place_tag.get_text(strip=True) if place_tag else ""

                extracted_data.append({
                    "イベント名": title,
                    "日付": date_text,
                    "場所": place_text,
                    "リンクURL": link_url
                })
            except:
                continue

    except Exception as e:
        st.error(f"致命的なエラー: {e}")
    finally:
        driver.quit()
    
    return extracted_data, status_log

# --- サイドバー設定 ---
with st.sidebar:
    st.header("設定")
    target_url = st.text_input("ターゲットURL", "https://example.com/events") # デフォルト値は適宜変更してください
    max_clicks = st.slider("「もっと見る」最大クリック回数", 1, 50, 30)
    
    st.info("※クリック回数が多いほど時間がかかります。(30回で約1〜2分)")

# --- メインエリア ---
if st.button("取得開始", type="primary"):
    if not target_url:
        st.error("URLを入力してください。")
    else:
        with st.spinner("ブラウザを起動してアクセスしています..."):
            data, logs = scrape_with_selenium(target_url, max_clicks)
        
        # ログの表示（折りたたみ）
        with st.expander("実行ログを確認"):
            for log in logs:
                st.write(f"- {log}")
        
        if data:
            st.success(f"{len(data)} 件のデータを取得しました！")
            
            df = pd.DataFrame(data)
            
            # 1. テーブル表示
            st.dataframe(
                df,
                use_container_width=True,
                column_config={
                    "リンクURL": st.column_config.LinkColumn("リンク")
                }
            )
            
            # 2. CSVダウンロード
            csv = df.to_csv(index=False).encode('utf-8_sig')
            st.download_button(
                label="📥 CSVをダウンロード",
                data=csv,
                file_name="selenium_events.csv",
                mime='text/csv'
            )
        else:
            st.warning("データが見つかりませんでした。HTMLクラス名が合っているか確認してください。")
