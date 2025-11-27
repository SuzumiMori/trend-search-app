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
st.markdown("信頼できる情報ソース（Fashion Press, PR TIMES等）に限定して検索します。")

# --- サイドバー: 設定エリア ---
with st.sidebar:
    st.header("検索条件")
    st.markdown("### 📍 地域・場所")
    region = st.text_input("検索したい場所", value="東京都渋谷区", help="具体的な地名を入力してください。")

    st.markdown("---")
    
    st.markdown("### 📅 期間指定")
    today = datetime.date.today()
    next_month = today + datetime.timedelta(days=30)
    
    start_date = st.date_input("開始日", today)
    end_date = st.date_input("終了日", next_month)

# --- メインエリア ---

if st.button("検索開始", type="primary"):
    try:
        api_key = st.secrets["GOOGLE_API_KEY"]
    except:
        st.error("⚠️ APIキーが設定されていません。")
        st.stop()

    if start_date > end_date:
        st.error("⚠️ 終了日は開始日より後の日付にしてください。")
    else:
        # 検索処理
        client = genai.Client(api_key=api_key)
        status_text = st.empty()
        status_text.info(f"🔍 {region}周辺の情報を収集中... (信頼できるメディアのみを検索中)")

        # 検索範囲（月単位）
        search_months = f"{start_date.year}年{start_date.month}月"
        if start_date.month != end_date.month:
            search_months += f"、{end_date.year}年{end_date.month}月"

        # ★ここがポイント：検索対象ドメインを指定
        trusted_sites = "site:fashion-press.net OR site:prtimes.jp OR site:walkerplus.com OR site:timeout.jp OR site:entabe.jp OR site:event-checker.info"

        # プロンプト
        prompt = f"""
        あなたは厳格なトレンドリサーチャーです。
        以下の「信頼できるサイト」のみを対象にGoogle検索を行い、正確なイベント情報を抽出してください。
        
        【検索クエリの指示】
        以下のキーワードで検索してください：
        「{region} イベント {search_months} {trusted_sites}」
        「{region} 新規オープン {search_months} {trusted_sites}」

        【ユーザー指定期間】
        {start_date} から {end_date} まで

        【出力形式（JSONのみ）】
        Markdown装飾不要。以下のJSONリストのみ出力してください。
        [
            {{
                "type": "種別(新メニュー/オープン/イベント)",
                "name": "店名またはイベント名",
                "place": "具体的な場所",
                "start_date": "YYYY-MM-DD",
                "end_date": "YYYY-MM-DD",
                "description": "概要",
                "source_name": "サイト名(例: Fashion Press)",
                "url": "記事のURL",
                "lat": 緯度(数値),
                "lon": 経度(数値)
            }},
            ...
        ]

        【絶対ルール】
        1. **指定した信頼できるサイト(Fashion Press, PR TIMES等)の情報のみを採用してください。** 怪しいブログやまとめサイトは無視してください。
        2. **URLは検索結果に出てきた実在するものをそのままコピーしてください。** 自分で推測してURLを作らないでください（リンク切れの原因になります）。
        3. 昨年の記事（2023年など）は絶対に除外してください。

        【条件】
        - 5件程度抽出してください。
        - 万が一情報が見つからない場合は、無理に捏造せず、見つかった件数だけで出力してください。
        """

        try:
            # AIにリクエスト
            response = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    tools=[types.Tool(google_search=types.GoogleSearch())],
                    response_mime_type="application/json"
                )
            )

            status_text.empty()
            
            # --- JSONデータの抽出・修復ロジック ---
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
            
            if not data:
                st.warning("条件に合う情報が見つかりませんでした。期間や地域を変更して再度お試しください。")
                st.stop()

            # --- 期間表示用の整形処理 ---
            for item in data:
                s_date = item.get('start_date')
                e_date = item.get('end_date')
                if s_date and e_date:
                    if s_date == e_date:
                        item['display_date'] = s_date
                    else:
                        item['display_date'] = f"{s_date} 〜 {e_date}"
                else:
                    item['display_date'] = s_date or "日付不明"

            # データフレーム変換
            df = pd.DataFrame(data)

            # --- 1. 高機能地図の表示 (Voyagerスタイル) ---
            st.subheader(f"📍 {region}周辺のイベントマップ")
            
            if not df.empty and 'lat' in df.columns and 'lon' in df.columns:
                map_df = df.dropna(subset=['lat', 'lon'])
                
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
                    gaiyou = f"【期間】{row.get('display_date')}\n{row.get('description')}"
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
                st.warning("地図データが取得できませんでした。")

            # --- 2. 速報テキストリスト ---
            st.markdown("---")
            st.subheader("📋 イベント情報一覧")
            st.caption("※信頼できるメディア（Fashion Press等）の記事へのリンクです。")
            
            for item in data:
                url_text = "なし"
                source_label = item.get('source_name', '詳細記事')
                
                if item.get('url'):
                    url_text = f"[🔗 {source_label} で記事を読む]({item.get('url')})"

                st.markdown(f"""
                - **期間**: {item.get('display_date')}
                - **種別**: {item.get('type')}
                - **店名/イベント名**: {item.get('name')}
                - **場所**: {item.get('place')}
                - **概要**: {item.get('description')}
                - **ソース**: {url_text}
                """)

        except Exception as e:
            status_text.empty()
            st.error(f"予期せぬエラーが発生しました: {e}")
