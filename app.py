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
st.markdown("信頼できる情報ソースから、**実在が確認された情報のみ**を表示します。")

# --- サイドバー: 設定エリア ---
with st.sidebar:
    st.header("検索条件")
    st.markdown("### 📍 地域・場所")
    region = st.text_input("検索したい場所", value="東京都渋谷区", help="具体的な地名を入力してください。")

    st.markdown("---")
    
    st.markdown("### 📅 期間指定")
    st.caption("※期間を短くしすぎると情報が見つからない場合があります。自動的にその月全体の情報を検索し、近いものを表示します。")
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
        
        # ★ここが改良点: 検索対象を「ピンポイントの日付」から「月単位」に自動拡大する
        # ユーザーが「11/29」を指定しても、検索は「2025年11月」全体で行うことでヒット率を高める
        search_months = set()
        search_months.add(f"{start_date.year}年{start_date.month}月")
        search_months.add(f"{end_date.year}年{end_date.month}月")
        search_months_str = " ".join(search_months) # 例: "2025年11月 2025年12月"

        status_text.info(f"🔍 {region}周辺の情報を収集中... (ヒット率を上げるため {search_months_str} の情報を広く探しています)")

        # 信頼できるサイトドメイン
        trusted_sites = "site:fashion-press.net OR site:prtimes.jp OR site:walkerplus.com OR site:timeout.jp OR site:entabe.jp OR site:event-checker.info"

        # プロンプト (ロボットモード)
        prompt = f"""
        あなたは「Web検索結果からのデータ抽出ロボット」です。創作能力はありません。
        以下の検索クエリでGoogle検索を行い、実在するイベント情報だけを抽出してください。

        【検索クエリ】
        「{region} イベント {search_months_str} {trusted_sites}」
        「{region} 新規オープン {search_months_str} {trusted_sites}」

        【ユーザーの希望期間】
        {start_date} から {end_date} まで

        【厳守ルール】
        1. **検索結果にないイベントを絶対に創作しないでください。** 情報が少なければ、無理に5件埋めなくて構いません。
        2. **URLは検索結果のものをそのまま使用してください。**
        3. **期間の許容:** ユーザーの希望期間にドンピシャの情報がない場合でも、「その月({search_months_str})」に開催されるイベントであれば候補として抽出してください。
        4. 昨年の情報（2023年など）は除外してください。

        【出力形式（JSONのみ）】
        [
            {{
                "type": "種別",
                "name": "店名またはイベント名",
                "place": "具体的な場所",
                "start_date": "YYYY-MM-DD",
                "end_date": "YYYY-MM-DD",
                "description": "概要",
                "source_name": "サイト名",
                "url": "記事のURL",
                "lat": 緯度(数値),
                "lon": 経度(数値)
            }}
        ]
        """

        try:
            # AIにリクエスト (temperature=0.0 で嘘を抑制)
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
            
            # データが空だった場合
            if not data:
                st.warning(f"⚠️ {region} エリアの指定期間における、信頼できるソースからの情報は現在見つかりませんでした。")
                st.info("💡 ヒント: まだ情報が公開されていないか、エリアを広げると見つかる可能性があります。")
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

            # --- 1. 高機能地図 (Voyager) ---
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
            st.caption("※AIの自動抽出情報です。リンク先で詳細をご確認ください。")
            
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
