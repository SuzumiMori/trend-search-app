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
st.markdown("指定した地域の「現在開催中」または「今後オープン/開催予定」の最新情報を検索します。")

# --- サイドバー: 設定エリア ---
with st.sidebar:
    st.header("検索条件")
    st.markdown("### 📍 地域・場所")
    region = st.text_input("検索したい場所", value="東京都渋谷区", help="具体的な地名を入力してください。")
    
    st.info("💡 期間指定をなくし、AIが「今話題」または「これから話題」になる情報を自動でピックアップします。")

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
    status_text.info(f"🔍 {region}の最新トレンド情報を収集中... (開催中・オープン予定)")

    # 今日の日付
    today = datetime.date.today()
    
    # 信頼できるサイトドメイン
    trusted_sites = "site:fashion-press.net OR site:prtimes.jp OR site:walkerplus.com OR site:timeout.jp OR site:entabe.jp OR site:event-checker.info"

    # プロンプト (期間縛りをなくし、状態(開催中/予定)で探させる)
    prompt = f"""
    あなたは「Web検索結果からのデータ抽出ロボット」です。
    以下の検索クエリでGoogle検索を行い、**「現在開催中」**または**「今後開催/オープン予定」**の具体的な情報を抽出してください。

    【検索クエリ】
    「{region} イベント 開催中 {trusted_sites}」
    「{region} イベント 開催予定 {trusted_sites}」
    「{region} 新規オープン 予定 {trusted_sites}」
    「{region} 限定メニュー 発売 {trusted_sites}」

    【基準日】
    本日は {today} です。これより過去に終了したイベントは除外してください。

    【厳守ルール】
    1. **具体的でない情報は破棄してください。** (例: 名前が「イベント」だけ、場所が「渋谷」だけのものは不可)
    2. **記事一覧ページやタグ一覧ページのURLは禁止です。** 必ず個別の記事URLを採用してください。
    3. 情報が見つからない場合は無理に埋めず、件数が少なくても確実なものだけを出力してください。
    4. 店名やイベント名が「unknown」や「不明」になるものは出力しないでください。

    【出力形式（JSONのみ）】
    [
        {{
            "type": "種別(新メニュー/オープン/イベント)",
            "name": "店名またはイベント名(必須)",
            "place": "具体的な場所(必須)",
            "start_date": "YYYY-MM-DD (不明ならnull)",
            "end_date": "YYYY-MM-DD (不明ならnull)",
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
                temperature=0.0  # 嘘をつかせない
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
        
        # --- クリーニング処理（変なデータを除去） ---
        cleaned_data = []
        for item in data:
            # 名前がunknown、あるいは空欄のものは捨てる
            name = item.get('name', '').lower()
            if not name or name == 'unknown' or name == 'イベント' or name == '情報なし':
                continue
            # URLがないものも捨てる
            if not item.get('url'):
                continue
            cleaned_data.append(item)
            
        data = cleaned_data

        # データが空だった場合
        if not data:
            st.warning(f"⚠️ {region} エリアの最新情報は、信頼できるソースからは見つかりませんでした。")
            st.info("💡 ヒント: エリア名を「渋谷区」から「渋谷」や「表参道」のように変えると見つかる場合があります。")
            st.stop()

        # --- 期間表示用の整形処理 ---
        for item in data:
            s_date = item.get('start_date')
            e_date = item.get('end_date')
            
            # 日付が入っていない場合の処理
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
        st.subheader(f"📍 {region}周辺のトレンドマップ")
        
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
