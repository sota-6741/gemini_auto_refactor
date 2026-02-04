# 自動リファクタリングエージェント

## agent_server.py

このスクリプトは、指定されたディレクトリ内のPythonファイルの変更を監視し、変更が検知されると自動的にGemini CLIを使用して関数型プログラミングの原則に基づいたリファクタリングを試みるサーバーアプリケーションです。

### 概要

FastAPIとWebSocketを使用して構築されており、リファクタリングの結果（元のコードとリファクタリング後のコードの差分）をリアルタイムでWebブラウザ上に表示します。

### 主な機能

1.  **ファイル監視**
    - `watchdog` ライブラリを使用し、指定ディレクトリ（再帰的）内の `.py` ファイルの保存イベントを監視します。
    - `agent_server.py` 自身は監視対象から除外されます。

2.  **自動リファクタリング**
    - ファイルの変更を検知すると、`refactor_prompt.txt` のプロンプトと対象コードを結合し、外部コマンド（`gemini`）を実行します。
    - 関数型プログラミングスタイルへの書き換えを指示します。

3.  **リアルタイムWeb UI**
    - WebSocketを通じて、処理状態（開始、Gemini処理中、完了、エラー）をブラウザにプッシュ通知します。
    - リファクタリング前後のコードを `diff2html` を用いてSide-by-Sideの差分形式で表示します。
    - リファクタリング後のコードをクリップボードにコピーする機能を提供します（HTTPS非対応環境向けのフォールバック機能付き）。

### 構成

プロジェクトは以下のディレクトリ構成を前提としています。

- `agent_server.py`: メインサーバーロジック
- `refactor_prompt.txt`: Gemini-cliへのプロンプト
- `templates/index.html`: WebフロントエンドのHTML
- `static/css/style.css`: スタイルシート
- `static/js/main.js`: WebSocket通信とUIロジック

### 依存関係

このプロジェクトを実行するには、以下の環境とライブラリが必要です。

#### 外部コマンド
- **Gemini CLI**: `gemini` コマンドがパスに通っているか、`/usr/local/bin/gemini` に配置されている必要があります。

#### Pythonライブラリ
以下のパッケージのインストールが必要です。

```bash
pip install fastapi uvicorn watchdog
```
依存関係の解決は以下のコマンドで
```bash
uv sync
```

### 使い方

以下のコマンドでサーバーを起動します。引数を省略した場合はカレントディレクトリを監視します。

```bash
python agent_server.py [監視するディレクトリパス]
```

起動後、ブラウザで `http://localhost:8000` にアクセスしてください。

### 技術スタック

- **Python**: FastAPI, Uvicorn, Watchdog
- **Frontend**: HTML5, CSS3, JavaScript (Vanilla)
- **Library**: Diff2Html (CDN経由)
