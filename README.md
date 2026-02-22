# TOEICLearnAgent (簡易 README)

TOEIC Part 5 学習用対話コンソール。ここでは「事前手順」と「実行方法」だけを示します。

## 事前手順 (Prerequisites)
1. Python 3.9 以上をインストール
2. Azure サブスクリプション & Azure AI Foundry プロジェクト作成済み
3. Chat Completions 対応モデルをデプロイ (例: `gpt-5-mini`)
4. RBAC: プロジェクトに「Azure AI User」ロール付与
5. ローカルで `az login` を実行し認証済みであること
6. 仮想環境作成 (推奨)
	- Windows (PowerShell):
	  ```powershell
	  python -m venv .venv
	  .\.venv\Scripts\Activate.ps1
	  ```
	- macOS / Linux:
	  ```bash
	  python3 -m venv .venv
	  source .venv/bin/activate
	  ```
	解除: `deactivate`
7. 依存インストール (仮想環境有効化後):
	```powershell
	pip install -r requirements.txt
	```
8. 環境変数設定（`.env` 推奨）
	```env
	PROJECT_ENDPOINT="https://<resource>.services.ai.azure.com/api/projects/<project-name>"  # 必須
	MODEL_DEPLOYMENT_NAME="gpt-5-mini"    # 任意(省略可)
	AGENT_ID=""                            # 既存エージェント再利用時のみ
	```

## 実行方法 (Run)
PowerShell (Windows):
```powershell
az login  # 未ログインの場合のみ
python agents_toeic_console.py
```

起動後、例: `穴埋め問題を1問ください` と入力。終了は `q` または Ctrl+C / EOF。

以上。必要に応じて終了後 `deactivate` で仮想環境を解除してください。
