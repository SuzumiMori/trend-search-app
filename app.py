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
            contents=prompt
