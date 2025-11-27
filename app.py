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
st.markdown("信頼できる情報ソースから、**年号が一致する確実な情報のみ**を表示します。")

# --- サイドバー: 設定エリア ---
with st.sidebar:
    st.header("検索条件")
    st.markdown("### 📍 地域・場所")
    region = st.text_input("検索したい場所", value="東京都渋谷区", help="具体的な地名を入力してください。")
    
    st.info("💡 検索精度を高めるため、自動的に「今年」または「来年」の年号を含む記事のみを厳選します。")

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
    
    # 今日の日付とターゲット年
    today = datetime.date.today()
    target_year = today.year
    
    status_text.info(f"🔍 {region}の情報を検索中... ({target_year}年の記事のみを厳選)")

    # 信頼できるサイトドメイン
    trusted_sites = "site:fashion-press.net OR site:prtimes.jp OR site:walkerplus.com OR site:timeout.jp OR site:entabe.jp OR site:event-checker.info"

    # プロンプト
    prompt = f"""
    あなたは「Web検索結果からのデータ抽出ロボット」です。
    以下の検索クエリでGoogle検索を行い、**「{target_year}年」に開催/オープン**される情報を抽出してください。

    【検索クエリ】
    「{region} イベント {target_year}年 開催中 {trusted_sites}」
    「{region} イベント {target_year}年 開催予定 {trusted_sites}」
    「{region} 新規オープン {target_year}年 {trusted_sites}」

    【基準日】
    本日は {today} です。これより過去に終了したイベントは除外してください。

    【厳守ルール：年号チェック】
    1. **記事のタイトルや本文に「{target_year}」または「{target_year}年」という表記が明確にあるものだけを選んでください。**
    2. 年号が見つからない、または去年の年号の記事は絶対に含めないでください。
    3. URLは検索結果のものをそのまま使用してください。捏造禁止。
    4. 該当情報がない場合は、空のリスト `[]` を返してください。

    【出力形式（JSONのみ）】
    [
        {{
            "type": "種別(新メニュー/オープン/イベント)",
            "name": "店名またはイベント名",
            "place": "具体的な場所",
            "start_date": "YYYY-MM-DD",
            "end_date": "YYYY-MM-DD",
            "description": "概要",
            "source_name": "サイト名",
            "url": "記事のURL",
            "found_year": "記事内で確認できた年号(例: 2025)",
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
                        candidate = match.group(0)
                        data = json.loads(candidate)
            except:
                pass
        
        # --- ★最強のフィルタリング処理 ---
        # AIが持ってきたデータでも、年号が間違っていたらここで捨てる
        cleaned_data = []
        for item in data:
            # 1. 名前がないものは捨てる
            name = item.get('name', '').lower()
            if not name or name in ['unknown', 'イベント', '情報なし']:
                continue
            
            # 2. URLがないものは捨てる
            if not item.get('url'):
                continue

            # 3. 【重要】年号チェック
            # AIが報告してきた「found_year」か、日付データの中に「ターゲット年」が含まれているか確認
            is_valid_year = False
            
            # AIが報告した年号をチェック
            found_year_str = str(item.get('found_year', ''))
            if str(target_year) in found_year_str:
                is_valid_year = True
            
            # 開始日の中に年号が含まれているかチェック
            elif item.get('start_date') and str(target_year) in str(item.get('start_date')):
                is_valid_year = True

            # 4. 過去の日付チェック (終了日が昨日より前のものは捨てる)
            is_future = True
            if item.get('end_date'):
                try:
                    e_date_obj = datetime.datetime.strptime(item.get('end_date'), "%Y-%m-%d").date()
                    if e_date_obj < today:
                        is_future = False
                except:
                    pass # 日付変換エラーならスルー

            # 合格したものだけ残す
            if is_valid_year and is_future:
                cleaned_data.append(item)
            
        data = cleaned_data

        # データが空だった場合
        if not data:
            st.warning(f"⚠️ {target_year}年の最新情報は、現在信頼できるソースからは見つかりませんでした。")
            st.info(f"💡 AIはいくつかの候補を見つけましたが、{target_year}年の確証が得られなかったため除外しました。")
            st.stop()

        # --- 期間表示用の整形処理 ---
        for item in data:
            s_date = item.get('start_date')
            e_date = item.get('end_date')
            
            if not s_date:
                item['display_date'] = "開催中/近日"
            elif s_date and e_date:
                if s_date == e_date:
                    item['display_date'] = s_date
                else:
                    item['display_date'] = f"{s_date} 〜 {e_date}"
            else:
                item['display_date'] = s_date

        # データフレーム変換
        df = pd.DataFrame(data)

        # --- 1. 高機能地図 (Voyager) ---
        st.subheader(f"📍 {region}周辺のトレンドマップ ({target_year}年版)")
        
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
        st.subheader("📋 最新トレンド情報一覧")
        
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
