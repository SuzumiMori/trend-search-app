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

# ページの設定
st.set_page_config(page_title="トレンド・イベント検索", page_icon="🗺️")

st.title("🗺️ トレンド・イベントMap検索")
st.markdown("指定した「イベントまとめサイト」のリストから、情報を一括抽出します。")

# --- サイドバー: 設定エリア ---
with st.sidebar:
    st.header("検索条件")
    st.markdown("### 📍 地域・場所")
    region = st.text_input("検索したい場所", value="東京都渋谷区", help="具体的な地名を入力してください。")
    
    st.markdown("---")
    st.markdown("### 🌐 対象サイト選択")
    
    # 検索対象サイトの定義
    SITE_OPTIONS = {
        "Walkerplus (イベント全般)": "walkerplus.com",
        "GO TOKYO (公式観光情報)": "gotokyo.org",
        "Lets Enjoy Tokyo (おでかけ)": "enjoytokyo.jp",
        "Fashion Press (新店・グッズ)": "fashion-press.net",
        "Event Checker (イベント)": "event-checker.info",
        "PR TIMES (公式プレスリリース)": "prtimes.jp",
        "TimeOut Tokyo (シティガイド)": "timeout.jp"
    }
    
    selected_sites = st.multiselect(
        "情報を取得するサイト（複数可）",
        options=list(SITE_OPTIONS.keys()),
        default=["Walkerplus (イベント全般)", "GO TOKYO (公式観光情報)", "Lets Enjoy Tokyo (おでかけ)"]
    )
    
    st.info("💡 選択したサイトの「イベント一覧ページ」を検索し、そこにある情報を読み取ります。")

# --- メインエリア ---

if st.button("検索開始", type="primary"):
    try:
        api_key = st.secrets["GOOGLE_API_KEY"]
    except:
        st.error("⚠️ APIキーが設定されていません。")
        st.stop()

    if not selected_sites:
        st.error("⚠️ 検索対象サイトを少なくとも1つ選択してください。")
        st.stop()

    # 検索処理
    client = genai.Client(api_key=api_key)
    status_text = st.empty()
    status_text.info(f"🔍 {region}の情報を、指定されたまとめサイトから抽出中... (目標: 20件以上)")

    # 選択されたドメインをリスト化
    target_domains = [SITE_OPTIONS[name] for name in selected_sites]
    
    # 検索クエリ作成 (site:A OR site:B ...)
    site_query = " OR ".join([f"site:{d}" for d in target_domains])
    
    # プロンプト
    prompt = f"""
    あなたは「Webページのリスト情報を構造化データに変換するスクレイピングボット」です。
    以下の検索クエリでGoogle検索を行い、検索結果に出てくる**イベント一覧ページ**の内容から、イベント情報を可能な限り多く抽出してください。

    【検索クエリ】
    「{region} イベント一覧 開催中 {site_query}」
    「{region} イベント カレンダー 今後 {site_query}」
    「{region} 新店 オープン情報 {site_query}」

    【抽出対象】
    現在開催中、または今後開催予定のイベント・新店情報。
    
    【厳守ルール】
    1. **件数重視**: リストにある情報は片っ端から拾ってください（最大20〜30件）。
    2. **URLの扱い**: 
       - 基本的に「検索結果のURL（まとめページのURL）」ではなく、**記事内に記載されている「個別のイベント詳細URL」**があればそれを優先してください。
       - なければ「まとめページのURL」で構いません。
       - **架空のURL（kanko.walkerplus など）は絶対に作成禁止**です。
    3. **実在性**: サイトに載っているものだけを出力してください。

    【出力形式（JSONのみ）】
    [
        {{
            "name": "イベント名",
            "place": "開催場所",
            "date_info": "期間(例: 開催中〜12/25)",
            "description": "概要(短くてOK)",
            "source_name": "サイト名",
            "url": "URL",
            "lat": 緯度(数値・不明ならnull),
            "lon": 経度(数値・不明ならnull)
        }}
    ]
    """

    try:
        # AIにリクエスト
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())],
                response_mime_type="application/json",
                temperature=0.0
            )
        )

        status_text.empty()
        
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
        
        # --- 簡易URLチェック ---
        # 許可したドメイン、またはそのサブドメインであることを確認
        cleaned_data = []
        for item in data:
            name = item.get('name', '')
            url = item.get('url', '')
            
            if not name or name.lower() in ['unknown', 'イベント']:
                continue
            
            # URLの補正（もしhttpがなければGoogle検索へ）
            if not url or not url.startswith("http") or "kanko.walkerplus" in url:
                search_query = f"{item['name']} {item['place']} イベント"
                item['url'] = f"https://www.google.com/search?q={urllib.parse.quote(search_query)}"
                item['source_name'] = "Google検索"
            
            cleaned_data.append(item)
            
        data = cleaned_data

        if not data:
            st.warning(f"⚠️ 指定されたサイトからは情報が見つかりませんでした。サイトの選択を変えてみてください。")
            st.stop()

        # データフレーム変換
        df = pd.DataFrame(data)

        # --- 1. 高機能地図 (Voyager) ---
        st.subheader(f"📍 {region}周辺のイベントマップ")
        st.caption(f"抽出件数: {len(data)}件")
        
        # 緯度経度があるデータのみ地図表示
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
            
            # Google検索リンクに差し替わった場合の表記
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

    except Exception as e:
        status_text.empty()
        st.error(f"予期せぬエラーが発生しました: {e}")
