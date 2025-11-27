import streamlit as st
import datetime
from google import genai
from google.genai import types
import os
import json
import pandas as pd
import re
import pydeck as pdk

# ページの設定
st.set_page_config(page_title="トレンド・イベント検索", page_icon="🗺️")

st.title("🗺️ トレンド・イベントMap検索")
st.markdown("大手イベント情報サイト（Enjoy Tokyo, Walkerplusなど）のリストから情報を一括抽出します。")

# --- サイドバー: 設定エリア ---
with st.sidebar:
    st.header("検索条件")
    st.markdown("### 📍 地域・場所")
    region = st.text_input("検索したい場所", value="東京都渋谷区", help="具体的な地名を入力してください。")
    
    st.info("💡 ヒット件数を増やすため、まとめサイトのリスト情報をそのまま抽出します。")

# --- メインエリア ---

if st.button("検索開始", type="primary"):
    try:
        api_key = st.secrets["GOOGLE_API_KEY"]
    except:
        st.error("⚠️ APIキーが設定されていません。")
        st.stop()

    # 検索処理
    client = genai.Client(api_key=api_key)
    status_text = st.empty()
    status_text.info(f"🔍 {region}のイベント情報を、まとめサイトから一括収集中...")

    # 今日の日付
    today = datetime.date.today()
    
    # 検索対象（リスト形式で情報を持っているサイト）
    target_sites = "site:enjoytokyo.jp OR site:walkerplus.com OR site:rurubu.jp OR site:jorudan.co.jp OR site:event-checker.info OR site:fashion-press.net"

    # プロンプト (まとめサイトのリスト読み取りに特化)
    prompt = f"""
    あなたは「イベント情報リストの抽出ロボット」です。
    以下の検索クエリでGoogle検索を行い、検索結果に出てくる**イベント情報まとめサイトのリスト**から、現在開催中または今後開催のイベントを可能な限り多く抽出してください。

    【検索クエリ】
    「{region} イベント一覧 開催中 {target_sites}」
    「{region} イベント一覧 今後 {target_sites}」
    「{region} 新店 オープン情報 {target_sites}」

    【抽出ルール（重要）】
    1. **URLについて**: 個別のイベント詳細ページを探す必要はありません。**「情報を見つけたまとめサイトのURL（検索結果のURL）」をそのまま `url` 欄に入れてください。**
       (これでリンク切れを防ぎます)
    2. **件数について**: 検索結果のスニペットに表示されているイベント名はすべて拾ってください。目標は10件以上です。
    3. **実在性**: まとめサイトに掲載されているものだけを抽出してください。創作禁止。

    【出力形式（JSONのみ）】
    [
        {{
            "name": "イベント名",
            "place": "開催場所(施設名など)",
            "date_info": "期間(例: 開催中〜12/25)",
            "description": "概要(短くてOK)",
            "source_name": "掲載サイト名(例: Enjoy Tokyo)",
            "url": "その情報が載っているまとめサイトのURL",
            "lat": 緯度(数値・不明ならエリア中心),
            "lon": 経度(数値・不明ならエリア中心)
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
                        candidate = match.group(0)
                        data = json.loads(candidate)
            except:
                pass
        
        # クリーニング
        cleaned_data = []
        for item in data:
            if not item.get('name') or item.get('name') in ['unknown', '情報なし']:
                continue
            cleaned_data.append(item)
        data = cleaned_data

        if not data:
            st.warning(f"⚠️ 情報が見つかりませんでした。")
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
                 st.warning("位置情報が取得できませんでした（リストのみ表示します）")
        else:
            st.warning("地図データが取得できませんでした。")

        # --- 2. 速報テキストリスト ---
        st.markdown("---")
        st.subheader("📋 イベント情報一覧")
        st.caption("※リンク先は情報元のまとめサイト等です。")
        
        for item in data:
            url_text = "なし"
            source_label = item.get('source_name', '掲載サイト')
            
            if item.get('url'):
                # リンク先がまとめサイトであることを明示
                url_text = f"[🔗 {source_label} で一覧を見る]({item.get('url')})"

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
