import streamlit as st
import datetime
from google import genai
from google.genai import types
import os
import json
import pandas as pd
import pydeck as pdk
import requests
from bs4 import BeautifulSoup
import time
import urllib.parse

# ページの設定
st.set_page_config(page_title="トレンド・イベント検索", page_icon="📖", layout="wide")

st.title("📖 イベント情報「一括直読」抽出アプリ")
st.markdown("指定したWebページをAIが読み込み、情報を統合・整理してテーブル表示します。")

# --- サイドバー: 設定エリア ---
with st.sidebar:
    st.header("読み込み対象 (複数選択可)")
    
    PRESET_URLS = {
        "Walkerplus (今日のイベント/東京)": "https://www.walkerplus.com/event_list/today/ar0300/",
        "Walkerplus (今週末のイベント/東京)": "https://www.walkerplus.com/event_list/weekend/ar0300/",
        "Walkerplus (来週のイベント/東京)": "https://www.walkerplus.com/event_list/next_week/ar0300/",
        "Let's Enjoy Tokyo (現在開催中/渋谷)": "https://www.enjoytokyo.jp/event/list/area1302/?date_type=current",
        "Let's Enjoy Tokyo (今週末/渋谷)": "https://www.enjoytokyo.jp/event/list/area1302/?date_type=weekend",
        "Fashion Press (最新ニュース)": "https://www.fashion-press.net/news/",
        "TimeOut Tokyo (東京のイベント)": "https://www.timeout.jp/tokyo/ja/things-to-do"
    }
    
    selected_presets = st.multiselect(
        "プリセットから選択",
        options=list(PRESET_URLS.keys()),
        default=["Walkerplus (今日のイベント/東京)", "Let's Enjoy Tokyo (現在開催中/渋谷)"]
    )
    
    st.markdown("---")
    st.markdown("### 🔗 カスタムURL")
    custom_urls_text = st.text_area(
        "その他のURL（改行区切りで複数入力可）",
        placeholder="https://...\nhttps://...",
        height=100
    )

    st.info("💡 「きょうから」等の表現は、具体的な日付に変換されます。")

# --- Session State ---
if 'extracted_data' not in st.session_state:
    st.session_state.extracted_data = None
if 'last_update' not in st.session_state:
    st.session_state.last_update = None

# --- メインエリア ---

if st.button("一括読み込み開始", type="primary"):
    try:
        api_key = st.secrets["GOOGLE_API_KEY"]
    except:
        st.error("⚠️ APIキーが設定されていません。")
        st.stop()

    # ターゲットリスト作成
    targets = []
    for label in selected_presets:
        targets.append({"url": PRESET_URLS[label], "label": label})
    
    if custom_urls_text:
        for url in custom_urls_text.split('\n'):
            url = url.strip()
            if url and url.startswith("http"):
                domain = urllib.parse.urlparse(url).netloc
                targets.append({"url": url, "label": f"カスタム ({domain})"})
    
    unique_targets = {t['url']: t for t in targets}
    targets = list(unique_targets.values())

    if not targets:
        st.error("⚠️ URLが指定されていません。")
        st.stop()

    all_data = []
    client = genai.Client(api_key=api_key)
    today = datetime.date.today()
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    total_urls = len(targets)
    
    # --- ループ処理 ---
    for i, target in enumerate(targets):
        url = target['url']
        label = target['label']
        
        progress_bar.progress(i / total_urls)
        status_text.info(f"⏳ ({i+1}/{total_urls}) 読み込み中...: {label}")
        
        try:
            # スクレイピング
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"}
            response = requests.get(url, headers=headers, timeout=15)
            response.encoding = response.apparent_encoding
            
            if response.status_code != 200:
                st.warning(f"⚠️ アクセス失敗: {url}")
                continue

            soup = BeautifulSoup(response.text, "html.parser")
            for script in soup(["script", "style", "nav", "footer", "iframe", "header"]):
                script.decompose()
            page_text = soup.get_text(separator="\n", strip=True)[:50000]

            # AI解析 (プロンプトを強化)
            prompt = f"""
            あなたはデータ抽出アシスタントです。
            以下のWebページのテキストから「イベント情報」を抽出し、JSON形式でリスト化してください。

            【前提情報】
            ・本日の日付: {today.strftime('%Y年%m月%d日')}
            ・ページURL: {url}
            ・サイト名: {label}

            【テキスト内容】
            {page_text}

            【抽出ルール（重要）】
            1. イベント名、期間、場所、概要を抽出してください。
            2. **日付の具体化**: テキスト内の「きょうから」「明日開催」「今週末」といった相対的な表現は禁止です。
               - 記事内に記載されている「公開日」や「イベント期間（例: 2025.11.28〜）」を探し、必ず**「YYYY年MM月DD日〜」のような具体的な日付形式**に変換してください。
               - どうしても日付が特定できない場合のみ、原文のままにしてください。
            3. 場所の緯度経度（lat, lon）は、場所名から推測して埋めてください。
            4. `source_url` はこのページのURL({url})としてください。

            【出力形式（JSONのみ）】
            [
                {{
                    "name": "イベント名",
                    "place": "開催場所",
                    "date_info": "期間(具体的な日付で)",
                    "description": "概要(簡潔に)",
                    "lat": 緯度(数値),
                    "lon": 経度(数値)
                }}
            ]
            """

            ai_response = client.models.generate_content(
                model="gemini-2.0-flash-exp",
                contents=prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.0)
            )
            
            extracted_list = json.loads(ai_response.text.replace("```json", "").replace("```", "").strip())
            
            if isinstance(extracted_list, list):
                for item in extracted_list:
                    item['source_label'] = label
                    item['source_url'] = url
                    all_data.append(item)
            
            time.sleep(1)

        except Exception as e:
            st.warning(f"スキップしました: {label} (エラー: {e})")
            continue

    progress_bar.progress(100)
    time.sleep(0.5)
    progress_bar.empty()

    if not all_data:
        st.error("情報が見つかりませんでした。")
        st.session_state.extracted_data = None
    else:
        # 重複削除
        unique_data = []
        seen_keys = set()
        for item in all_data:
            name_key = str(item.get('name', '')).replace(" ", "").replace("　", "").lower()
            place_key = str(item.get('place', '')).replace(" ", "").replace("　", "").lower()
            if not name_key: continue
            unique_key = (name_key, place_key)
            if unique_key not in seen_keys:
                seen_keys.add(unique_key)
                unique_data.append(item)
        
        st.session_state.extracted_data = unique_data
        st.session_state.last_update = datetime.datetime.now().strftime("%H:%M:%S")
        status_text.success(f"🎉 読み込み完了！ ({st.session_state.last_update})")

# --- 結果表示エリア ---

if st.session_state.extracted_data is not None:
    data = st.session_state.extracted_data
    df = pd.DataFrame(data)

    st.markdown(f"**最終更新: {st.session_state.last_update}** ({len(data)}件)")

    # 1. マップ表示
    st.subheader("📍 イベントマップ")
    if not df.empty and 'lat' in df.columns and 'lon' in df.columns:
        map_df = df.dropna(subset=['lat', 'lon'])
        if not map_df.empty:
            view_state = pdk.ViewState(
                latitude=map_df['lat'].mean(),
                longitude=map_df['lon'].mean(),
                zoom=11,
                pitch=0,
            )
            layer = pdk.Layer(
                "ScatterplotLayer",
                map_df,
                get_position='[lon, lat]',
                get_color='[255, 75, 75, 160]',
                get_radius=300,
                pickable=True,
            )
            st.pydeck_chart(pdk.Deck(
                map_style='https://basemaps.cartocdn.com/gl/voyager-gl-style/style.json',
                initial_view_state=view_state,
                layers=[layer],
                tooltip={"html": "<b>{name}</b><br/>{place}<br/><i>{date_info}</i>"}
            ))

    # 2. テーブル表示
    st.markdown("---")
    st.subheader("📋 イベント一覧")

    display_cols = ['date_info', 'name', 'place', 'description', 'source_label', 'source_url']
    available_cols = [c for c in display_cols if c in df.columns]
    display_df = df[available_cols].copy()
    
    rename_map = {
        'date_info': '期間', 'name': 'イベント名', 'place': '場所', 
        'description': '概要', 'source_label': '情報源', 'source_url': 'リンクURL'
    }
    display_df = display_df.rename(columns=rename_map)

    st.dataframe(
        display_df,
        use_container_width=True,
        column_config={
            "リンクURL": st.column_config.LinkColumn("元記事", display_text="🔗 リンクを開く"),
            "概要": st.column_config.TextColumn("概要", width="large")
        },
        hide_index=True
    )

    # 3. CSVダウンロード
    csv = display_df.to_csv(index=False).encode('utf-8_sig')
    st.download_button(
        label="📥 CSVをダウンロード",
        data=csv,
        file_name="events_list.csv",
        mime='text/csv'
    )
