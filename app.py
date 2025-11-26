import streamlit as st
import datetime
from google import genai
from google.genai import types

# ページの設定
st.set_page_config(page_title="トレンド・イベント検索", page_icon="🔍")

st.title("🔍 トレンド・イベント検索アプリ")
st.markdown("指定した期間の「新メニュー」「新規オープン」「イベント」情報をAIが検索します。")

# --- サイドバー: 設定エリア ---
with st.sidebar:
    st.header("設定")
    # APIキーの入力（パスワードのように隠して入力できます）
    # ※自分だけで使うなら st.secrets から読み込むのが安全ですが、
    #  簡易的に共有するなら、ユーザーに入れてもらう方式が一番トラブルが少ないです。
    api_key = st.text_input("Gemini APIキー", type="password", help="ここにAPIキーを入力してください")
    
    st.markdown("---")
    st.markdown("### 期間指定")
    # 日付選択（デフォルトは今日〜1ヶ月後）
    today = datetime.date.today()
    next_month = today + datetime.timedelta(days=30)
    
    start_date = st.date_input("開始日", today)
    end_date = st.date_input("終了日", next_month)

# --- メインエリア ---

if st.button("検索開始", type="primary"):
    if not api_key:
        st.error("⚠️ 左側のサイドバーにAPIキーを入力してください。")
    elif start_date > end_date:
        st.error("⚠️ 終了日は開始日より後の日付にしてください。")
    else:
        # 検索処理
        client = genai.Client(api_key=api_key)
        
        status_text = st.empty()
        status_text.info("🔍 Webから情報を収集中... (20〜30秒ほどかかります)")

        # プロンプトの作成（選択された日付を埋め込む）
        prompt = f"""
        あなたはトレンドリサーチャーです。
        日本国内における、【{start_date}】から【{end_date}】までの期間の以下の情報を、Google検索を使って調べてください。

        【調査対象】
        1. 有名チェーン店や人気飲食店の「新メニュー」「期間限定メニュー」の発売情報
        2. 注目の「新規店舗オープン」情報（商業施設や話題の店）
        3. 期間限定のイベント情報

        【条件】
        - 情報源は信頼できるニュースサイトやプレスリリースなどを優先してください。
        - **厳選して5〜10件** 抽出してください。
        - 過去のイベントではなく、指定期間に含まれるものに限ります。
        - 出力はMarkdown形式で、読みやすい箇条書きにしてください。
        """

        try:
            # AIにリクエスト
            response = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    tools=[types.Tool(google_search=types.GoogleSearch())]
                )
            )

            # 結果表示
            status_text.empty() # 検索中の文字を消す
            st.success("検索完了！")
            st.markdown(response.text)

            # 参照元リンクの表示
            with st.expander("📚 参考にしたWebページ"):
                if response.candidates[0].grounding_metadata.grounding_chunks:
                    for chunk in response.candidates[0].grounding_metadata.grounding_chunks:
                        if chunk.web:
                            st.markdown(f"- [{chunk.web.title}]({chunk.web.uri})")

        except Exception as e:
            status_text.empty()
            st.error(f"エラーが発生しました: {e}")
