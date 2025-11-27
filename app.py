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
st.markdown("信頼できる情報サイトから、「期間限定のイベント」や「新店情報」のみを厳選して抽出します。")

# --- サイドバー: 設定エリア ---
with st.sidebar:
    st.header("検索条件")
    st.markdown("### 📍 地域・場所")
    region = st.text_input("検索したい場所", value="東京都渋谷区", help="具体的な地名を入力してください。")
    
    st.markdown("---")
    st.markdown("### 🌐 検索対象サイト")
    
    SITE_DOMAINS = {
        "Walkerplus": "walkerplus.com",
        "GO TOKYO": "gotokyo.org",
        "Let's Enjoy Tokyo": "enjoytokyo.jp",
        "Fashion Press": "fashion-press.net",
        "TimeOut Tokyo": "timeout.jp",
        "Jorudan": "jorudan.co.jp",
        "PR TIMES": "prtimes.jp"
    }
    
    selected_sites = st.multiselect(
        "情報を取得するサイト（複数可）",
        options=list(SITE_DOMAINS.keys()),
        default=["Walkerplus", "Let's Enjoy Tokyo", "Fashion Press"]
    )
    
    st.info("💡 施設そのものの紹介（スポット情報）は自動的に除外します。")

# --- メインエリア ---

if st.button("検索開始", type="primary"):
    # 事前チェック
    try:
        api_key = st.secrets["GOOGLE_API_KEY"]
    except:
        st.error("⚠️ APIキーが設定されていません。")
        st.stop()

    if not selected_sites:
        st.error("⚠️ 検索対象サイトを少なくとも1つ選択してください。")
        st.stop()

    try:
        # 検索処理準備
        client = genai.Client(api_key=api_key)
        status_text = st.empty()
        status_text.info(f"🔍 {region}のイベント情報を収集中... (常設施設の除外処理中)")

        target_domains = [SITE_DOMAINS[name] for name in selected_sites]
        site_query = " OR ".join([f"site:{d}" for d in target_domains])
        
        today = datetime.date.today()
        
        # ★ここが重要: 検索クエリを「期間限定」寄りに修正
        prompt = f"""
        あなたは「イベント情報の選別ロボット」です。
        以下の検索クエリを使い、Google検索結果から**期間限定のイベント**や**新規オープン**の情報だけを抽出してください。

        【検索クエリ】
        「{region} イベント 期間限定 {site_query}」
        「{region} フェスティバル 開催 {site_query}」
        「{region} 新規オープン {site_query}」
        「{region} 展覧会 開催 {site_query}」

        【基準日】
        本日は {today} です。終了したイベントは除外してください。

        【厳守ルール：施設紹介の排除】
        1. **ただの「施設紹介」は絶対に含めないでください。**
           × 悪い例: 「明治神宮」「代々木公園」「渋谷ヒカリエ」 (これらは場所でありイベントではありません)
           ○ 良い例: 「明治神宮 秋の大祭」「代々木公園 わんわんカーニバル」「渋谷ヒカリエ クリスマスマーケット」
        2. **URL**: 検索結果の**記事URL**をそのまま使用してください。
        3. **件数**: 最大20件抽出してください。

        【出力形式（JSONのみ）】
        [
            {{
                "name": "イベント名(必須)",
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
        
        # 1.5-flash-002 で実行
        try:
            response = execute_search("gemini-1.5-flash-002")
        except Exception as e:
            error_msg = str(e)
            if "404" in error_msg or "NOT_FOUND" in error_msg:
                status_text.warning("⚠️ モデル切り替え中...")
                try:
                    time.sleep(2)
                    response = execute_search("gemini-2.0-flash-exp")
                except Exception as e2:
                    st.error(f"エラー: {e2}")
                    st.stop()
            else:
                st.error(f"エラーが発生しました: {e}")
                st.stop()

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
        
        # --- クリーニング & 施設除外ロジック ---
        cleaned_data = []
        for item in data:
            name = item.get('name', '')
            place = item.get('place', '')
            url = item.get('url', '')
            
            # 1. 名前がない、unknown等は削除
            if not name or name.lower() in ['unknown', 'イベント']:
                continue
            
            # 2. ★重要: 「イベント名」と「場所名」が酷似している場合は「施設紹介」とみなして削除
            # 例: name="代々木公園", place="代々木公園" -> 削除
            if name.replace(" ", "") == place.replace(" ", ""):
                continue

            # 3. URLチェック
            is_valid_source = False
            if url and url.startswith("http"):
                for domain in target_domains:
                    if domain in url:
                        is_valid_source = True
                        break
            
            if not is_valid_source:
                search_query = f"{item['name']} {item['place']} イベント"
                item['url'] = f"https://www.google.com/search?q={urllib.parse.quote(search_query)}"
                item['source_name'] = "Google検索"
            
            cleaned_data.append(item)
            
        data = cleaned_data

        if not data:
            st.warning(f"⚠️ 期間限定のイベントは見つかりませんでした。")
            st.info("「検索対象サイト」を変更するか、エリアを変えてみてください。")
            st.stop()

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
                        "
