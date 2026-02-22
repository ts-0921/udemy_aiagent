"""Azure AI Foundry Agents を利用した TOEIC Part 5 学習コンソール。

概要:
    対話型コンソールで TOEIC Part5 穴埋め問題を段階的に出題し、ユーザ解答に対して
    解説 + 次問題 を返す学習補助ツール。5問毎に弱点分析も追加する。

前提環境:
    - 依存インストール: ``pip install -r requirements.txt``
    - 認証: ``az login``（DefaultAzureCredential が利用する）
    - RBAC: プロジェクトに "Azure AI User" 権限
    - 環境変数設定:
            PROJECT_ENDPOINT=https://<resource>.services.ai.azure.com/api/projects/<project-name>
            MODEL_DEPLOYMENT_NAME=gpt-5-mini (任意、省略時 gpt-5-mini)
            AGENT_ID=<既存エージェントID> (任意)

主要フロー:
    1. 埋め込み済み instructions を用いてエージェント取得/作成
    2. 新規 thread を生成しユーザ入力を message として追加
    3. run の create_and_process でモデル推論 -> 応答表示
    4. (将来拡張余地) 応答テキストから正誤・弱点を抽出可能

簡易化している点:
    - Structured 出力/ツール利用なし（純テキスト）
    - 永続化: thread 上のメッセージ履歴のみ（外部DBなし）
    - キーワードベース弱点抽出は未実装（コメント方針のみ）

終了条件:
    - ユーザ入力 "q" / EOF / Ctrl+C

このファイルでは「可読性向上と保守容易性」を目的に要所へ詳細コメントを追加している。
"""
from __future__ import annotations
import os
from typing import List

from azure.ai.projects import AIProjectClient  # Azure AI Foundry (Projects SDK) クライアント
from azure.identity import DefaultAzureCredential
from azure.core.exceptions import HttpResponseError
from azure.ai.agents.models import ListSortOrder, MessageRole
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(__file__)

# instructions.md の内容を直接コード内に埋め込み（ローカルファイル依存をなくし、単一スクリプト配布を容易化）
BASE_INSTRUCTIONS = """## 役割
- あなたは、TOEIC Part5（短文穴埋め問題）の文法学習を支援する専門的な英語学習アシスタントです。
- 学習者のレベルに合わせて、適切な問題を出題し、詳細な解説を提供しながら、文法力向上をサポートしましょう。

## ふるまい
- 励ましの言葉を使いながら指導しましょう。
- 間違いを恐れずに学習できる安心感のある環境を提供しましょう。
- 問題は一問ずつ出しましょう。
- ユーザ回答後は、日本語で解説をし、英語の例文には日本語訳を併記しましょう。
- ユーザ回答後の解説時に、続けて次の問題を提示しましょう。
- 5問ごとに、今までの学習内容から、ユーザが苦手とする領域を分析して、アドバイスしましょう。"""

load_dotenv()  # .env が存在すれば読み込む

PROJECT_ENDPOINT = os.environ.get("PROJECT_ENDPOINT")  # 必須: AI Project のエンドポイント URL
MODEL_DEPLOYMENT = os.environ.get("MODEL_DEPLOYMENT_NAME", "gpt-5-mini")  # 任意: デプロイ済みモデル名 (既定: gpt-5-mini)
EXISTING_AGENT_ID = os.environ.get("AGENT_ID")  # 任意: 既存エージェント再利用時の ID（新規作成を避ける）

if not PROJECT_ENDPOINT:
    raise SystemExit("環境変数 PROJECT_ENDPOINT が設定されていません。")

# 認証: Entra ID (ローカルでは az login 済み前提)
project = AIProjectClient(
    credential=DefaultAzureCredential(),
    endpoint=PROJECT_ENDPOINT,
)

def ensure_agent(instructions: str):
    """エージェントを取得または新規作成する。

    挙動:
      - 環境変数 EXISTING_AGENT_ID があれば get_agent を試行
      - 取得失敗 (404/権限エラーなど) は即座に SystemExit で終了しユーザへ通知
      - 未指定または存在しなければ create_agent で新規作成

    引数:
      instructions: モデルへ渡す system/instructions 相当のガイドテキスト

    戻り値:
      tuple(agent, created_new)
        agent: 取得/作成されたエージェントオブジェクト
        created_new: 新規作成した場合 True / 既存利用 False
    """
    if EXISTING_AGENT_ID:
        try:
            ag = project.agents.get_agent(EXISTING_AGENT_ID)
            return ag, False
        except HttpResponseError as e:
            raise SystemExit(f"既存エージェント取得失敗: {e}")
    agent = project.agents.create_agent(
        model=MODEL_DEPLOYMENT,
        name="toeic-learn-agent",
        instructions=instructions,
    )
    print(f"Created agent ID: {agent.id}")
    return agent, True

def create_thread():
    """対話コンテキスト(thread)を新規作成する。

    モデルは thread 内の全メッセージ履歴を参照できるため、学習セッション単位で 1 つ作成。
    （複数スレッド併用は未実装。必要なら並列利用も可能）
    """
    thread = project.agents.threads.create()
    print(f"Created thread ID: {thread.id}")
    return thread

def append_user_message(thread_id: str, content: str):
    """ユーザ入力を thread に追加する。

    role=USER のメッセージを積み上げることで、モデル側は履歴を踏まえた応答が可能。
    """
    project.agents.messages.create(
        thread_id=thread_id,
        role=MessageRole.USER,
        content=content,
    )


def run_agent(thread_id: str, agent_id: str):
    """与えられた thread 上で agent を実行し、推論完了まで待機する。

    create_and_process:
        - 非同期 run 作成 + 完了待機 をまとめて行う便利メソッド。
    失敗時:
        - run.status == 'failed' なら RuntimeError を送出し上位でリトライ/通知可能。
    戻り値:
        完了した run オブジェクト（成功時）
    """
    run = project.agents.runs.create_and_process(
            thread_id=thread_id,
            agent_id=agent_id,
    )
    if run.status == "failed":
            raise RuntimeError(f"Run failed: {run.last_error}")
    return run

def fetch_messages(thread_id: str) -> List[str]:
    """thread 内の全メッセージ（テキスト部のみ）を昇順で取得し最新状態を再構築する。

    注意:
        - 各 message には複数 text chunk があり得るため、末尾要素のみを採用
        - 添付ファイルや画像等のサポートは本サンプルでは未対応
    戻り値:
        テキスト文字列のリスト（古い -> 新しい）
    """
    msgs = project.agents.messages.list(thread_id=thread_id, order=ListSortOrder.ASCENDING)
    out: List[str] = []
    for m in msgs:
            if m.text_messages:  # テキストが存在するメッセージのみ抽出
                    out.append(m.text_messages[-1].text.value)
    return out

# ===== メインループ =====

def safe_delete_agent(agent_id: str):
    """（新規作成した場合のみ）エージェントを削除する安全策。

    理由:
      サンプル実行毎に不要なエージェントを蓄積させないため。
    挙動:
      - 正常削除成功でログ出力
      - 既に削除/不存在 (404) は静かに成功扱い（並行実行や失敗ロールバックで消えている場合がある）
      - その他 HttpResponseError は警告表示
    """
    try:
        project.agents.delete_agent(agent_id)
        print(f"Cleaned up agent {agent_id}")
    except HttpResponseError as e:  # サービスからのHTTP系例外
        # 環境差異や直前失敗により既に消えている場合を許容
        msg = str(e).lower()
        if "no assistant" in msg or e.status_code == 404:
            print(f"Agent {agent_id} は既に存在しません (404)。クリーンアップ不要。")
        else:
            print(f"エージェント削除警告: {e}")
    except Exception as e:
        print(f"エージェント削除予期せぬ例外: {e}")


def main():
    """コンソール対話メインループ。

    構造:
      1. エージェント/スレッド初期化
      2. ユーザ入力待ち (空行はスキップ)
      3. 'q' / EOF / Ctrl+C で終了
      4. 入力 -> メッセージ追加 -> 推論実行 -> 応答表示

    例外ハンドリング方針:
      - HttpResponseError: サービス側エラー -> 再入力促し継続
      - その他 Exception: ログ出力のみ継続（学習セッション中断を避ける）
      - KeyboardInterrupt: Graceful にクリーンアップ
    """
    print("Azure AI Foundry Agents チャットコンソール\n終了: q / Ctrl+C\n")
    instructions = BASE_INSTRUCTIONS
    agent, created_new = ensure_agent(instructions)
    thread = create_thread()
    print("最初のメッセージを入力してください。例: '穴埋め問題を1問ください'\n")

    try:
        while True:
            try:
                user_text = input("ユーザー > ").strip()
            except EOFError:
                # パイプやリダイレクト利用時などに EOF が来たら即終了
                print("\nEOF 受信: 終了します。")
                break
            if user_text.lower() == "q":  # 'q' で明示終了
                print("終了します。")
                break
            if not user_text:  # 空行は無視して再入力
                continue
            try:
                append_user_message(thread.id, user_text)
                run_agent(thread.id, agent.id)
                show_latest(thread.id)
            except HttpResponseError as e:
                print(f"サービスエラー: {e}\n再度入力してください。")
            except Exception as e:
                print(f"予期せぬエラー: {e}\n続行します。")
    except KeyboardInterrupt:
        print("\nCtrl+C 受信: 終了処理中 ...")
    finally:
        # 新規作成したエージェントのみ削除（既存はユーザが継続利用できるよう保持）
        if created_new:
            safe_delete_agent(agent.id)
        else:
            print("既存エージェントは保持しました。")
        print("Graceful shutdown 完了。")


def show_latest(thread_id: str) -> str:
    """最新のエージェント応答を取得し整形表示する。

    返却値は最新テキスト（存在しない場合 "(no messages)"）。
    """
    messages = fetch_messages(thread_id)
    latest = messages[-1] if messages else "(no messages)"
    print(f"""
--- Agent 応答 ---
{latest}
------------------""")
    return latest

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"エラー: {e}")
