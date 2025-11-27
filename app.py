import streamlit as st
import datetime
from google import genai
from google.genai import types
import os
import json
import pandas as pd
import re
import pydeck as pdk
import urllib.parse # URL解析用

# ページの設定
st.set_page_config(page_title="トレンド・イベント検索", page_icon="🗺️")

st.title("🗺️ トレンド・イベントMap検索")
st.markdown("信頼できる大手情報サイトから、安全なリンクのみを厳選して表示します。")

# --- サイドバー: 設定エリア ---
with st.sidebar:
    st.header("検索条件")
    st.markdown("### 📍 地域・場所")
    region = st.text_input("検索したい場所", value="東京都渋谷区", help="具体的な地名を入力してください。")
    
    st.info("💡 リンク切れを防ぐため、公式サイトや大手メディアの正しいURLのみを表示します。")

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
    status_text.info(f"🔍 {region}のイベント情報を収集中... (URLの安全性チェック中)")

    # 許可するドメイン（ホワイトリスト）
    # ここに含まれないドメインのURLは「怪しい」とみなして弾きます
    VALID_DOMAINS = [
        "walkerplus.com",
        "enjoytokyo.jp",
        "rurubu.jp",
        "jorudan.co.jp",
        "fashion-press.net",
        "prtimes.jp",
        "timeout.jp",
        "event-checker.info",
        "entabe.jp",
        "lmaga.jp",      # 関西系に強い
        "letsenjoytokyo.jp"
    ]

    # プロンプト
    target_sites = " OR ".join([f"site:{d}" for d in VALID_DOMAINS])
    
    prompt = f"""
    あなたは「イベント情報抽出のプロ」です。
    以下の検索クエリでGoogle検索を行い、**現在開催中**または**今後開催予定**のイベント情報を抽出してください。

    【検索クエリ】
    「{region} イベント一覧 開催中 {target_sites}」
    「{region} 新規オープン 予定 {target_sites}」

    【厳守ルール】
    1. **実在する正しいURLのみ抽出してください。** `kanko.walkerplus.com` のような架空のサブドメインは絶対に禁止です。
    2. URLが不明確な場合は `null` にしてください。
    3. イベント名は正確に拾ってください。「unknown」は禁止です。

    【出力形式（JSONのみ）】
    [
        {{
            "name": "イベント名",
            "place": "開催場所",
            "date_info": "期間(例: 開催中〜12/25)",
            "description": "概要",
            "source_name": "サイト名",
            "url": "記事のURL",
            "lat": 緯度(数値),
            "lon": 経度(数値)
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
        
        # --- ★URL検問（ホワイトリスト・チェック） ---
        cleaned_data = []
        for item in data:
            name = item.get('name', '')
            url = item.get('url', '')
            
            # 1. 名前チェック
            if not name or name.lower() in ['unknown', 'イベント', '情報なし']:
                continue
            
            # 2. URLドメインチェック
            is_valid_url = False
            if url and url.startswith("http"):
                try:
                    domain = urllib.parse.urlparse(url).netloc
                    # ホワイトリストのいずれかがドメインに含まれているか
                    for valid_d in VALID_DOMAINS:
                        if valid_d in domain:
                            is_valid_url = True
                            break
                    
                    # 特定の幻覚URLは名指しで排除
                    if "kanko.walkerplus" in url:
                        is_valid_url = False
                        
                except:
                    is_valid_url = False
            
            # URLが怪しい場合の救済措置
            # URLを削除するのではなく、「Google検索結果へのリンク」に差し替える
            if not is_valid_url:
                search_query = f"{item['name']} {item['place']} イベント"
                item['url'] = f"https://www.google.com/search?q={urllib.parse.quote(search_query)}"
                item['source_name'] = "Google検索" # ソース名も変更
            
            cleaned_data.append(item)
            
        data = cleaned_data

        if not data:
            st.warning(f"⚠️ 信頼できる情報が見つかりませんでした。")
            st.stop()

        # データフレーム変換
        df = pd.DataFrame(data)

        # --- 1. 高機能地図 (Voyager) ---
        st.subheader(f"📍 {region}周辺のイベントマップ")
        
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

        # --- 2. 速報テキストリスト ---
        st.markdown("---")
        st.subheader("📋 イベント情報一覧")
        st.caption("※リンク先で詳細をご確認ください。")
        
        for item in data:
            url_text = "なし"
            source_label = item.get('source_name', '詳細')
            
            # Google検索リンクに差し替わった場合の表記
            link_label = f"{source_label} で確認"
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
