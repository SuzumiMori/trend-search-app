import streamlit as st
import datetime
from google import genai
from google.genai import types
import os
import json
import pandas as pd
import re
import pydeck as pdk
import urllib.parse
import time

# ページの設定
st.set_page_config(page_title="トレンド・イベント検索", page_icon="🗺️")

st.title("🗺️ トレンド・イベントMap検索")
st.markdown("高性能AIモデル(Pro版)を使用し、Web上の記事を時間をかけて精査します。")

# --- サイドバー: 設定エリア ---
with st.sidebar:
    st.header("検索条件")
    st.markdown("### 📍 地域・場所")
    region = st.text_input("検索したい場所", value="東京都渋谷区", help="具体的な地名を入力してください。")
    
    st.markdown("---")
    st.markdown("### 🌐 検索対象サイト")
    
    SITE_PATHS = {
        "Fashion Press (ニュース)": "fashion-press.net/news/",
        "Walkerplus (イベント記事)": "walkerplus.com/article/",
        "Walkerplus (イベントリスト)": "walkerplus.com/event_list/",
        "Let's Enjoy Tokyo (イベント)": "enjoytokyo.jp/event/",
        "TimeOut Tokyo (ガイド)": "timeout.jp/tokyo/ja/things-to-do/",
        "PR TIMES (プレスリリース)": "prtimes.jp/main/html/rd/p/",
        "FASHIONSNAP (ニュース)": "fashionsnap.com/article/"
    }
    
    selected_labels = st.multiselect(
        "検索対象（複数選択可）",
        options=list(SITE_PATHS.keys()),
        default=["Fashion Press (ニュース)", "Walkerplus (イベント記事)", "Let's Enjoy Tokyo (イベント)"]
    )
    
    st.info("💡 精度重視の「Proモデル」を使用するため、検索には30秒〜1分程度かかります。")

# --- メインエリア ---

if st.button("検索開始", type="primary"):
    try:
        api_key = st.secrets["GOOGLE_API_KEY"]
    except:
        st.error("⚠️ APIキーが設定されていません。")
        st.stop()

    if not selected_labels:
        st.error("⚠️ 検索対象を少なくとも1つ選択してください。")
        st.stop()

    # 進捗バー
    progress_bar = st.progress(0)
    status_text = st.empty()

    # STEP 1: 準備
    status_text.info("🚀 検索エンジンを起動中...")
    time.sleep(1)
    progress_bar.progress(10)
    
    client = genai.Client(api_key=api_key)
    target_paths = [SITE_PATHS[label] for label in selected_labels]
    
    # 検索クエリ作成
    site_query = " OR ".join([f"site:{path}" for path in target_paths])
    today = datetime.date.today()

    # プロンプト (Proモデル向け)
    prompt = f"""
    あなたは「高精度なファクトチェック・ロボット」です。
    Google検索を行い、以下の条件に合致するイベント情報を慎重に抽出してください。

    【検索クエリ】
    「{region} イベント 開催中 {site_query}」
    「{region} 新規オープン 決定 {site_query}」

    【基準日】
    本日は {today} です。終了済みのイベントは除外してください。

    【最重要ルール：URLの実在確認】
    1. **URLの推測・創作は厳禁です。** 2. **検索結果に表示されている「リンクそのもの」** をコピーして使用してください。
    3. 記事の個別URLが不明な場合は `null` にしてください。

    【出力形式（JSONのみ）】
    [
        {{
            "name": "イベント名",
            "place": "開催場所",
            "date_info": "期間(例: 11/1〜12/25)",
            "description": "概要(短くてOK)",
            "source_name": "サイト名",
            "url": "記事のURL",
            "lat": 緯度(数値・不明ならnull),
            "lon": 経度(数値・不明ならnull)
        }}
    ]
    """

    # STEP 2: 検索実行
    status_text.info(f"🔍 {region}周辺の情報を検索中... (Proモデルで詳細に解析します)")
    progress_bar.progress(30)

    # 検索実行関数
    def execute_search(model_name):
        return client.models.generate_content(
            model=model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())],
                response_mime_type="application/json",
                temperature=0.0
            )
        )

    response = None
    
    # ★修正箇所：モデル名を標準的なものに変更
    try:
        # 1. まずは「Pro」を試す（最も賢い）
        response = execute_search("gemini-1.5-pro")
    except Exception as e:
        status_text.warning("⚠️ Proモデルの応答が遅いため、高速モデル(Flash)に切り替えます...")
        try:
            # 2. ダメなら「Flash」を試す（制限にかかりにくい）
            time.sleep(2)
            response = execute_search("gemini-1.5-flash")
        except Exception as e2:
            st.error(f"エラーが発生しました: {e2}")
            st.stop()

    # STEP 3: データの解析
    status_text.info("📝 取得した記事データの整合性とURLをチェック中...")
    progress_bar.progress(80)
    time.sleep(1)

    # --- JSONデータの抽出 ---
    text = response.text.replace("```json", "").replace("```", "").strip()
    data = []
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        try:
            if e.msg.startswith("Extra data"):
                data = json.loads(text[:e.pos])
            else:
                match = re.search(r'\[.*\]', text, re.DOTALL)
                if match:
                    data = json.loads(match.group(0))
        except:
            pass
    
    # --- クリーニング & URL物理フィルタリング ---
    cleaned_data = []
    for item in data:
        name = item.get('name', '')
        url = item.get('url', '')
        
        # 名前チェック
        if not name or name.lower() in ['unknown', 'イベント']:
            continue
        
        # URLチェック
        is_valid = False
        if url and url.startswith("http"):
            for path in target_paths:
                # パスのドメイン部分だけで簡易チェック
                check_domain = path.split('/')[0] 
                if check_domain in url:
                    is_valid = True
                    break
        
        # 幻覚URLブロック
        if "kanko.walkerplus" in url: is_valid = False

        if not is_valid:
            search_query = f"{item['name']} {item['place']} イベント"
            item['url'] = f"https://www.google.com/search?q={urllib.parse.quote(search_query)}"
            item['source_name'] = "Google検索"
        
        cleaned_data.append(item)
        
    data = cleaned_data

    # STEP 4: 完了
    progress_bar.progress(100)
    time.sleep(0.5)
    progress_bar.empty()

    if not data:
        status_text.error("条件に合う記事が見つかりませんでした。")
        st.stop()
    else:
        status_text.success(f"検索完了！ {len(data)}件の情報を取得しました。")

    # データフレーム変換
    df = pd.DataFrame(data)

    # --- 1. 高機能地図 (Voyager) ---
    st.subheader(f"📍 {region}周辺のイベントマップ")
    st.caption(f"抽出件数: {len(data)}件")
    
    if not df.empty and 'lat' in df.columns and 'lon' in df.columns:
        map_df = df.dropna(subset=['lat', 'lon'])
        
        if not map_df.empty:
            view_state = pdk.ViewState(
                latitude=map_df['lat'].mean(),
                longitude=map_df['lon'].mean(),
                zoom=13,
                pitch=0,
            )

            layer = pdk.Layer(
                "ScatterplotLayer",
                map_df,
                get_position='[lon, lat]',
                get_color='[255, 75, 75, 160]',
                get_radius=200,
                pickable=True,
            )

            st.pydeck_chart(pdk.Deck(
                map_style='https://basemaps.cartocdn.com/gl/voyager-gl-style/style.json',
                initial_view_state=view_state,
                layers=[layer],
                tooltip={
                    "html": "<b>{name}</b><br/>{place}<br/><i>{description}</i>",
                    "style": {"backgroundColor": "steelblue", "color": "white"}
                }
            ))
            st.caption("※地図上の赤い丸にマウスを乗せると詳細が表示されます。")
            
            # CSV作成
            export_data = []
            for _, row in map_df.iterrows():
                gaiyou = f"【期間】{row.get('date_info')}\n{row.get('description')}"
                export_data.append({
                    "Name": row.get('name'),
                    "住所": row.get('place'),
                    "概要": gaiyou,
                    "公式サイト": row.get('url', '')
                })
            
            export_df = pd.DataFrame(export_data)
            csv = export_df.to_csv(index=False).encode('utf-8_sig')

            st.download_button(
                label="📥 Googleマイマップ用CSVをダウンロード",
                data=csv,
                file_name=f"event_map_{region}.csv",
                mime='text/csv',
                help="このファイルをGoogleマイマップにインポートし、「住所」列を目印の場所に指定してください。"
            )
        else:
             st.info("※位置情報が特定できなかったため、地図には表示されませんが、以下のリストには表示されています。")
    else:
        st.warning("地図データが取得できませんでした。")

    # --- 2. 速報テキストリスト ---
    st.markdown("---")
    st.subheader("📋 イベント情報一覧")
    
    for item in data:
        url_text = "なし"
        source_label = item.get('source_name', '掲載サイト')
        
        link_label = f"{source_label} で見る"
        if source_label == "Google検索":
            link_label = "🔍 Googleで再検索"

        if item.get('url'):
            url_text = f"[🔗 {link_label}]({item.get('url')})"

        st.markdown(f"""
        - **期間**: {item.get('date_info')}
        - **イベント名**: {item.get('name')}
        - **場所**: {item.get('place')}
        - **概要**: {item.get('description')}
        - **ソース**: {url_text}
        """)
